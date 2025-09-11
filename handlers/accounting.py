import re
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import ContextTypes
from db import (
    add_record, get_group_config, set_group_rate, set_group_fee,
    delete_records, remove_record_by_msgid, add_operator, remove_operator,
    get_operators, load_operators, set_group_daily_reset
)
from report import generate_bill
from db import get_wallet_addresses_db, add_wallet_address_db, delete_wallet_address_db

# ---------- 正则表达式 ----------
# 地址
add_addr_pattern = re.compile(r'^设置地址\s+([T1UQ][A-Za-z0-9]{33,48})\s*(.*)$')
del_addr_pattern = re.compile(r'^删除地址\s+([T1UQ][A-Za-z0-9]{33,48})$')
show_addr_pattern = re.compile(r'^显示地址$')
# 记账
calc_pattern = re.compile(r'^[\d\.\(\) ]+[\+\-\*/][\d\.\(\) \+\-\*/]*$')
quick_pattern = re.compile(r'^(?:([\u4e00-\u9fa5\w]+)?\+(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?)$')
send_pattern = re.compile(r"^下发(-?\d+(?:\.\d+)?)([Uu])?$")
cancel_pattern = re.compile(r"^撤销\s*([\u4e00-\u9fa5\w]+)?\s*(\d+(?:\.\d+)?)?$")
bill_pattern = re.compile(r'^\+0$')
set_rate_pattern = re.compile(r'^设置汇率[：: ]?\s*(\d+(\.\d+)?)$')
set_fee_pattern = re.compile(r'^设置费率[：: ]?\s*(\d+(\.\d+)?)$')
add_op_pattern = re.compile(r'^设置操作人\s+@(\w+)$')
del_op_pattern = re.compile(r'^删除操作人\s+@(\w+)$')
show_op_pattern = re.compile(r'^显示操作人$')
del_bill_pattern = re.compile(r'^删除账单$')
tron_pattern = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
ton_pattern = re.compile(r"^[UQ][A-Za-z0-9]{47,48}$")
set_reset_pattern = re.compile(r'^设置日切[：: ]?\s*(\d{1,2})$')

# ---------- 内存缓存 ----------
group_operators = {}  # 缓存操作人
address_records = {}  # 地址验证记录
group_activation_status = {}  # key: chat_id, value: set 已执行命令
REQUIRED_COMMANDS = {"开始"}  # 完整激活条件

# ---------- 辅助函数 ----------
def format_amount(amount: float) -> str:
    if amount is None:
        return "0"
    return str(int(amount)) if amount == int(amount) else f"{amount:.2f}"

def get_beijing_time():
    tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(tz)

def _norm_username(u: str) -> str:
    return (u or "").lstrip("@").lower()

# ---------- 权限检查 ----------
def is_super_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admin_ids = context.bot_data.get("SUPER_ADMIN_IDS", [])
    return user_id in admin_ids

def is_operator(chat_id: int, username: str) -> bool:
    ops = group_operators.get(chat_id, set())
    return _norm_username(username) in ops

def is_authorized(user_id: int, username: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return is_super_admin(user_id, context) or is_operator(chat_id, username)

# ---------- 初始化操作人 ----------
def init_operators():
    load_operators()

# ---------- 主入口 ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return False

    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.full_name
    text = update.message.text.strip()

    # 禁止私聊
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ 此机器人仅支持群组使用")
        return False

    # ---------- 激活模块 ----------
    if text == "开始":
        group_activation_status.setdefault(chat_id, set()).add("开始")
        await update.message.reply_text("✅ 已执行开始命令")
        return False

    # 初始化群组操作人缓存
    if chat_id not in group_operators:
        operators = get_operators(chat_id)
        group_operators[chat_id] = set(operators)

    # ---------- 地址验证 ----------
    if tron_pattern.match(text) or ton_pattern.match(text):
        addr = text
        rec = address_records.setdefault(addr, {"count": 0, "last_user": None})
        rec["count"] += 1
        last_user = rec["last_user"]
        rec["last_user"] = f"@{username}"
        reply = f"地址：{addr}\n验证次数：{rec['count']}"
        if last_user:
            reply += f"\n上次发送：{last_user}\n本次发送：@{username}"
        else:
            reply += f"\n首次发送：@{username}"
        await update.message.reply_text(reply)
        return False

    # ---------- 显示账单 ----------
    if bill_pattern.match(text):
        bill_text, bill_markup = generate_bill(chat_id)
        await context.bot.send_message(chat_id=chat_id, text=bill_text, reply_markup=bill_markup)
        return False

    # ---------- 计算器 ----------
    if calc_pattern.match(text):
        if text.startswith("+") or text.isdigit():
            return False
        try:
            result = eval(text, {"__builtins__": None}, {})
            if isinstance(result, (int, float)):
                await update.message.reply_text(f"{format_amount(result)}")
                return False
        except Exception:
            return False

    # ---------- 快捷入款 ----------
    m = quick_pattern.match(text)
    if m:
        activated = group_activation_status.get(chat_id, set())
        if not REQUIRED_COMMANDS.issubset(activated):
            await update.message.reply_text("⚠️ 记账模块未激活，请先执行：开始")
            return False

        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以记账")
            return False

        remark = m.group(1)
        amount_rmb = float(m.group(2))
        group_conf = get_group_config(chat_id)
        rate = float(m.group(3)) if m.group(3) else group_conf["rate"]
        amount_usd = amount_rmb / rate
        display_name = remark.strip() if remark and remark.strip() else user.full_name or username

        record = {
            "type": "入款",
            "user": display_name,
            "display_name": display_name,
            "amount_rmb": amount_rmb,
            "amount_usd": amount_usd,
            "rate": rate,
            "operator": username,
            "time": get_beijing_time().strftime("%H:%M:%S"),
            "msg_id": update.message.message_id
        }

        try:
            add_record(chat_id, record)
        except Exception as e:
            await update.message.reply_text(f"⚠️ 记录失败: {e}")
            return False

        bill_text, bill_markup = generate_bill(chat_id)
        await context.bot.send_message(chat_id=chat_id, text=bill_text, reply_markup=bill_markup)
        return False

    # ---------- 下发 ----------
    m = send_pattern.match(text)
    if m:
        activated = group_activation_status.get(chat_id, set())
        if not REQUIRED_COMMANDS.issubset(activated):
            await update.message.reply_text("⚠️ 记账模块未激活，请先执行：开始")
            return False

        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以下发")
            return False

        raw_amount = float(m.group(1))
        is_usd = bool(m.group(2))
        group_conf = get_group_config(chat_id)
        rate = group_conf["rate"]
        amount_usd, amount_rmb = (raw_amount, raw_amount * rate) if is_usd else (raw_amount / rate, raw_amount)

        record = {
            "type": "下发",
            "user": username,
            "display_name": user.full_name or username,
            "amount_rmb": amount_rmb,
            "amount_usd": amount_usd,
            "rate": rate,
            "operator": username,
            "time": get_beijing_time().strftime("%m-%d %H:%M:%S"),
            "msg_id": update.message.message_id
        }

        try:
            add_record(chat_id, record)
        except Exception as e:
            await update.message.reply_text(f"⚠️ 下发记录失败: {e}")
            return False

        bill_text, bill_markup = generate_bill(chat_id)
        await context.bot.send_message(chat_id=chat_id, text=bill_text, reply_markup=bill_markup)
        return False

    # ---------- 设置汇率 ----------
    m = set_rate_pattern.match(text)
    if m:
        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以设置汇率")
            return False
        rate = float(m.group(1))
        set_group_rate(chat_id, rate)
        group_activation_status.setdefault(chat_id, set()).add("设置汇率")
        await update.message.reply_text(f"✅ 已设置汇率：{rate}")
        return False

    # ---------- 设置费率 ----------
    m = set_fee_pattern.match(text)
    if m:
        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以设置费率")
            return False
        fee = float(m.group(1))
        set_group_fee(chat_id, fee)
        group_activation_status.setdefault(chat_id, set()).add("设置费率")
        await update.message.reply_text(f"✅ 已设置费率：{fee}%")
        return False

    # ---------- 设置日切 ----------
    m = set_reset_pattern.match(text)
    if m:
        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以设置日切")
            return False
        hour = int(m.group(1))
        if not 0 <= hour <= 23:
            await update.message.reply_text("⚠️ 日切小时必须在 0~23 之间")
            return False
        set_group_daily_reset(chat_id, hour)
        await update.message.reply_text(f"✅ 已设置日切时间为每天 {hour} 点")
        return False

    # ---------- 删除账单 ----------
    if del_bill_pattern.match(text):
        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以删除账单")
            return False
        result = delete_records(chat_id)
        group_activation_status[chat_id] = set()
        await update.message.reply_text(f"{result}\n⚠️ 记账模块已重置，需要重新激活")
        return False

    # ---------- 撤销 ----------
    if text.startswith("撤销"):
        if not is_authorized(user.id, username, chat_id, context):
            await update.message.reply_text("⚠️ 只有超级管理员或操作人可以撤销")
            return False
        is_reply = update.message.reply_to_message is not None
        reply_msg_id = update.message.reply_to_message.message_id if is_reply else None
        if is_reply and reply_msg_id:
            result = remove_record_by_msgid(chat_id, reply_msg_id)
            await update.message.reply_text(result)
        else:
            await update.message.reply_text("⚠️ 撤销必须回复某条记账消息")
        return False

    # ---------- 操作人管理 ----------
    m = add_op_pattern.match(text)
    if m:
        if not is_super_admin(user.id, context):
            await update.message.reply_text("⚠️ 只有超级管理员可以添加操作人")
            return False
        op = m.group(1)
        add_operator(chat_id, op)
        group_operators.setdefault(chat_id, set()).add(op)
        await update.message.reply_text(f"✅ 已添加操作人 @{op}")
        return False

    m = del_op_pattern.match(text)
    if m:
        if not is_super_admin(user.id, context):
            await update.message.reply_text("⚠️ 只有超级管理员可以删除操作人")
            return False
        op = m.group(1)
        remove_operator(chat_id, op)
        group_operators.get(chat_id, set()).discard(op)
        await update.message.reply_text(f"🗑 已删除操作人 @{op}")
        return False

    if show_op_pattern.match(text):
        operators = get_operators(chat_id)
        ops = ", ".join([f"@{o}" for o in operators]) or "暂无"
        await update.message.reply_text(f"👥 当前操作人：{ops}")
        return False

    # 添加地址
    m = add_addr_pattern.match(text)
    if m:
        address = m.group(1)
        remark = m.group(2) or ""
        add_wallet_address_db(chat_id, address, remark)
        await update.message.reply_text(f"✅ 已添加地址：{address}\n备注：{remark}")
        return True

    # 删除地址
    m = del_addr_pattern.match(text)
    if m:
        address = m.group(1)
        deleted = delete_wallet_address_db(chat_id, address)
        if deleted:
            await update.message.reply_text(f"✅ 已删除地址：{address}")
        else:
            await update.message.reply_text(f"⚠️ 未找到地址：{address}")
        return True

    # 显示地址
    if show_addr_pattern.match(text):
        rows = get_wallet_addresses_db(chat_id)
        if not rows:
            await update.message.reply_text("⚠️ 本群暂无监控地址")
        else:
            msg_lines = ["📌 本群监控地址："]
            for r in rows:
                remark = f"（{r['remark']}）" if r['remark'] else ""
                msg_lines.append(f"{r['address']}{remark}")
            await update.message.reply_text("\n".join(msg_lines))
        return True

    return False
