import asyncio
import aiohttp
import json
import logging
import os
import math
from datetime import datetime
from typing import Dict, List, Optional
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
PERSISTENCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_tx_state.json")

# 存储已推送过的交易，避免重复推送
last_tx_map = {}

class TronListener:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.is_running = False

    async def load_persistence(self) -> None:
        """从文件加载持久化数据"""
        global last_tx_map
        try:
            with open(PERSISTENCE_FILE, 'r') as f:
                last_tx_map = json.load(f)
            logger.info(f"已加载 {len(last_tx_map)} 个地址的持久化数据")
        except FileNotFoundError:
            logger.info("未找到持久化文件，将从头开始监听")
        except Exception as e:
            logger.error(f"加载持久化数据时出错: {e}")

    async def save_persistence(self) -> None:
        """保存持久化数据到文件"""
        try:
            with open(PERSISTENCE_FILE, 'w') as f:
                json.dump(last_tx_map, f)
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
                        await asyncio.sleep(2 ** attempt)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"请求异常: {e}，尝试 {attempt + 1}/{retries}")
                await asyncio.sleep(2 ** attempt)
        logger.error(f"所有 {retries} 次尝试均失败: {url}")
        return None

    async def fetch_trc20_transactions(self, address: str, limit: int = 20) -> List[dict]:
        """调用 TRON 官方 API 获取 USDT(TRC20) 交易记录"""
        url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit={limit}&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_with_retry(session, url)
            return data.get("data", []) if data else []

    async def get_balance(self, address: str) -> float:
        """获取 TRC20 USDT 余额"""
        url = f"https://api.trongrid.io/v1/accounts/{address}"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_with_retry(session, url)
            if not data:
                return 0.0

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

    def format_address_short(self, address: str) -> str:
        """格式化地址显示为前 6 个字符"""
        return address[:6] if len(address) >= 6 else address

    def format_amount_precise(self, amount: float) -> str:
        """格式化金额显示，整数显示整数，小数保留两位，向下截断"""
        if amount == 0:
            return "0"
        if amount.is_integer():
            return str(int(amount))
        truncated = math.floor(amount * 100) / 100
        amount_str = str(truncated)
        if '.' in amount_str:
            integer_part, decimal_part = amount_str.split('.')
            if len(decimal_part) < 2:
                decimal_part = decimal_part.ljust(2, '0')
            return f"{integer_part}.{decimal_part}"
        else:
            return amount_str

    async def check_address(self, address_info: Dict) -> None:
        """检查单个地址的交易情况"""
        chat_id = address_info['chat_id']
        address = address_info['address']
        remark = address_info.get('remark', '')

        try:
            transactions = await self.fetch_trc20_transactions(address)
            if not transactions:
                return

            last_tx_id = last_tx_map.get(address)

            new_tx_list = []
            for tx in transactions:
                tx_id = tx.get("transaction_id")
                if last_tx_id is None or tx_id != last_tx_id:
                    new_tx_list.append(tx)
                else:
                    break

            if not new_tx_list:
                return

            last_tx_map[address] = new_tx_list[0]["transaction_id"]
            balance = await self.get_balance(address)

            msg_lines = [
                f"钱包报账 [{remark}]",
                "",
                f"💹USDT余额：{self.format_amount_precise(balance)}",
                "",
                f"钱包地址：{address}",
                "",
                "USDT流水："
            ]

            for tx in new_tx_list[:5]:
                block_timestamp = tx.get("block_timestamp")
                value = tx.get("value", "0")
                from_addr = tx.get("from")
                to_addr = tx.get("to")

                ts = datetime.fromtimestamp(block_timestamp / 1000).strftime("%m-%d %H:%M")
                amount = float(value) / 1_000_000

                is_deposit = to_addr.lower() == address.lower()
                counterparty = from_addr if is_deposit else to_addr
                counterparty_short = self.format_address_short(counterparty)
                amount_formatted = self.format_amount_precise(amount)
                direction = "转入" if is_deposit else "转出"
                msg_lines.append(f"{ts}    {counterparty_short}{direction}    {amount_formatted}")

            msg_text = "\n".join(msg_lines)
            await self.bot.send_message(chat_id=chat_id, text=msg_text)
            logger.info(f"已向聊天 {chat_id} 发送地址 {address} 的更新")

        except Exception as e:
            logger.error(f"处理地址 {address} 时出错: {e}")

    async def start_listening(self):
        """启动 TRON 监听器"""
        await self.load_persistence()
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

                semaphore = asyncio.Semaphore(5)

                async def limited_check(addr):
                    async with semaphore:
                        return await self.check_address(addr)

                tasks = [limited_check(addr) for addr in all_addresses]
                await asyncio.gather(*tasks, return_exceptions=True)

                save_counter += 1
                if save_counter >= 10:
                    await self.save_persistence()
                    save_counter = 0

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"TRON监听器主循环发生错误: {e}")
                await asyncio.sleep(60)

    async def stop_listening(self):
        """停止 TRON 监听器"""
        self.is_running = False
        await self.save_persistence()
        logger.info("TRON监听器已停止")
