import asyncio
import aiohttp
import json
import logging
import os
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
from telegram import Bot
from db import get_all_wallet_addresses

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tron_listener.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TRON_Listener")

# TRON 监听器配置
CHECK_INTERVAL = 45  # 每 45 秒检查一次
PERSISTENCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_tx_state.json")  # 持久化存储文件

# 用于保存已推送过的交易，避免重复推送
last_tx_map = {}
processed_tx_cache = {}  # 缓存每个地址已处理的交易ID

class TronListener:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.is_running = False
        
    async def load_persistence(self) -> None:
        """从文件加载持久化数据"""
        global last_tx_map, processed_tx_cache
        try:
            with open(PERSISTENCE_FILE, 'r') as f:
                data = json.load(f)
                last_tx_map = data.get('last_tx_map', {})
                processed_tx_cache = data.get('processed_tx_cache', {})
            logger.info(f"已加载 {len(last_tx_map)} 个地址的持久化数据")
            logger.info(f"已加载 {sum(len(v) for v in processed_tx_cache.values())} 个已处理交易记录")
        except FileNotFoundError:
            logger.info("未找到持久化文件，将从零开始监听")
        except Exception as e:
            logger.error(f"加载持久化数据时出错: {e}")

    async def save_persistence(self) -> None:
        """保存持久化数据到文件"""
        try:
            data = {
                'last_tx_map': last_tx_map,
                'processed_tx_cache': processed_tx_cache
            }
            with open(PERSISTENCE_FILE, 'w') as f:
                json.dump(data, f)
            logger.info("持久化数据已保存")
        except Exception as e:
            logger.error(f"保存持久化数据时出错: {e}")

    async def fetch_with_retry(self, session: aiohttp.ClientSession, url: str, retries: int = 3) -> Optional[dict]:
        """带重试机制的请求函数"""
        headers = {"accept": "application/json"}
        for attempt in range(retries):
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"请求失败，状态码: {resp.status}，尝试 {attempt + 1}/{retries}")
                        await asyncio.sleep(2 ** attempt)  # 指数退避
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"请求异常: {e}，尝试 {attempt + 1}/{retries}")
                await asyncio.sleep(2 ** attempt)
        
        logger.error(f"所有 {retries} 次尝试均失败: {url}")
        return None

    async def fetch_trc20_transactions(self, address: str, limit: int = 20) -> List[dict]:
        """
        调用TRON官方API获取USDT(TRC20)交易记录
        """
        url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit={limit}&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_with_retry(session, url)
            return data.get("data", []) if data else []

    async def get_balance(self, address: str) -> float:
        """
        获取TRC20 USDT余额 - 使用TRON官方API
        """
        url = f"https://api.trongrid.io/v1/accounts/{address}"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_with_retry(session, url)
            if not data:
                return 0.0
                
            # TRON官方API返回结构
            trc20_contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
            data_list = data.get("data", [])
            if not data_list:
                return 0.0
                
            account_data = data_list[0]
            trc20_balances = account_data.get("trc20", [])
            
            for balance_info in trc20_balances:
                if trc20_contract in balance_info:
                    return float(balance_info[trc20_contract]) / 1_000_000
                    
            return 0.0

    def format_amount_precise(self, amount: float) -> str:
        """
        格式化金额显示
        如果是整数就显示整数，有小数点的话保留小数点后两位
        不四舍五入，直接截断
        """
        if amount == 0:
            return "0"
        
        # 检查是否为整数
        if amount.is_integer():
            return str(int(amount))
        
        # 对于小数，保留两位小数（不四舍五入）
        # 使用向下取整的方式截断
        truncated = math.floor(amount * 100) / 100
        
        # 转换为字符串并确保格式正确
        amount_str = str(truncated)
        if '.' in amount_str:
            # 确保有两位小数
            integer_part, decimal_part = amount_str.split('.')
            if len(decimal_part) < 2:
                decimal_part = decimal_part.ljust(2, '0')
            return f"{integer_part}.{decimal_part}"
        else:
            return amount_str

    def format_address_short(self, address: str) -> str:
        """格式化地址显示为前6个字符（用于交易记录中的对方地址）"""
        return address[:6] if len(address) >= 6 else address

    async def check_address(self, address_info: Dict) -> None:
        """
        检查单个绑定地址的交易情况
        """
        chat_id = address_info['chat_id']
        address = address_info['address']
        remark = address_info.get('remark', '')
        
        try:
            transactions = await self.fetch_trc20_transactions(address)
            if not transactions:
                return

            # 初始化地址的处理交易缓存
            if address not in processed_tx_cache:
                processed_tx_cache[address] = set()
            
            # 筛选出新交易（不在已处理交易集中的交易）
            new_tx_list = []
            for tx in transactions:
                tx_id = tx.get("transaction_id")
                if tx_id not in processed_tx_cache[address]:
                    new_tx_list.append(tx)
                else:
                    # 遇到已处理交易，停止遍历（API返回按时间倒序）
                    break
            
            if not new_tx_list:
                return
                
            # 更新已处理交易集（最多保留最近50个交易ID）
            for tx in new_tx_list[:5]:  # 只处理最新的5笔交易
                tx_id = tx.get("transaction_id")
                processed_tx_cache[address].add(tx_id)
            
            # 限制每个地址的缓存大小
            if len(processed_tx_cache[address]) > 50:
                # 转换为列表，保留最新的50个
                tx_list = list(processed_tx_cache[address])
                processed_tx_cache[address] = set(tx_list[-50:])
            
            # 更新最后交易ID（使用最新的交易ID）
            last_tx_map[address] = new_tx_list[0]["transaction_id"]
            
            # 获取当前余额
            balance = await self.get_balance(address)
            
            # 按照指定模板构建推送消息
            msg_lines = [
                f"钱包报账[{remark}]",
                "",
                f"💹USDT余额：{self.format_amount_precise(balance)}",
                "",
                f"钱包地址：{address}",
                "",
                "USDT流水："
            ]
            
            # 添加新交易详情（最多5笔）
            for tx in new_tx_list[:5]:
                block_timestamp = tx.get("block_timestamp")
                value = tx.get("value", "0")
                from_addr = tx.get("from")
                to_addr = tx.get("to")
                
                # 格式化时间 - 修改为北京时间 (UTC+8)
                utc_time = datetime.utcfromtimestamp(block_timestamp / 1000)
                beijing_time = utc_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))
                ts = beijing_time.strftime("%m-%d %H:%M")
                
                amount = float(value) / 1_000_000
                
                # 判断交易方向
                is_deposit = to_addr.lower() == address.lower()
                
                # 格式化金额
                amount_formatted = self.format_amount_precise(amount)
                
                # 格式化对方地址（只显示前6个字符）
                counterparty_short = self.format_address_short(from_addr if is_deposit else to_addr)
                
                # 添加交易记录行
                if is_deposit:
                    # 转入：对方地址 + "转入"
                    msg_lines.append(f"{ts}    {counterparty_short}转入    {amount_formatted}")
                else:
                    # 转出："转出" + 对方地址
                    msg_lines.append(f"{ts}    转出{counterparty_short}    {amount_formatted}")
            
            # 发送消息
            msg_text = "\n".join(msg_lines)
            await self.bot.send_message(
                chat_id=chat_id, 
                text=msg_text
            )
            logger.info(f"已向聊天 {chat_id} 发送地址 {address} 的 {len(new_tx_list)} 笔新交易")
            
        except Exception as e:
            logger.error(f"处理地址 {address} 时出错: {e}")

    async def start_listening(self):
        """启动 TRON 监听器"""
        # 加载持久化数据
        await self.load_persistence()
        
        # 保存计数器（每10次循环保存一次持久化数据）
        save_counter = 0
        
        self.is_running = True
        logger.info("TRON监听推送已启动...")
        
        while self.is_running:
            try:
                all_addresses = get_all_wallet_addresses()
                if not all_addresses:
                    logger.info("未找到任何监控地址")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                    
                logger.info(f"开始检查 {len(all_addresses)} 个地址")
                
                # 使用Semaphore限制并发数量，避免过多请求
                semaphore = asyncio.Semaphore(5)
                
                async def limited_check(addr):
                    async with semaphore:
                        return await self.check_address(addr)
                
                tasks = [limited_check(addr) for addr in all_addresses]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # 每10次循环保存一次持久化数据
                save_counter += 1
                if save_counter >= 10:
                    await self.save_persistence()
                    save_counter = 0
                
                await asyncio.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"TRON监听器主循环发生错误: {e}")
                await asyncio.sleep(60)  # 出错时等待更长时间
    
    async def stop_listening(self):
        """停止 TRON 监听器"""
        self.is_running = False
        await self.save_persistence()
        logger.info("TRON监听器已停止")
