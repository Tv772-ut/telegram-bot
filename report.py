from db import get_records, get_group_config
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime
import pytz
import re

def get_beijing_time():
    tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(tz)

def format_number(num):
    """格式化数字：整数显示整数，小数最多显示两位"""
    if num is None:
        return "0"
    if num == int(num):
        return str(int(num))
    else:
        return f"{num:.2f}"

def format_time(dt):
    """格式化时间：只显示时:分:秒"""
    if isinstance(dt, str):
        try:
            if len(dt) == 8 and ":" in dt:  # HH:MM:SS
                return dt
            elif " " in dt:  # 含日期
                for fmt in ("%Y-%m-%d %H:%M:%S", "%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                    try:
                        dt_obj = datetime.strptime(dt, fmt)
                        return dt_obj.strftime("%H:%M:%S")
                    except:
                        continue
            if ":" in dt:
                time_match = re.search(r'(\d{1,2}:\d{1,2}:\d{1,2})', dt)
                if time_match:
                    return time_match.group(1)
        except:
            return dt
    elif isinstance(dt, datetime):
        return dt.strftime("%H:%M:%S")
    return str(dt)

def generate_bill(chat_id):
    records = get_records(chat_id)
    group_conf = get_group_config(chat_id)
    rate_fixed = group_conf['rate']
    fee = group_conf.get('fee', 0.0)

    income_records = []
    payout_records = []

    # 处理原始记录
    for record in records:
        r_type, user, display_name, amount_rmb, amount_usd, rate, operator, time_str = record
        formatted_time = format_time(time_str)

        if r_type == "入款":
            income_records.append((formatted_time, amount_rmb, amount_usd, display_name, rate, time_str))
        elif r_type == "下发":
            payout_records.append((formatted_time, amount_rmb, amount_usd, display_name, time_str))

    # ---------- 分类统计：只显示最新3个不同的操作人 ----------
    income_records_sorted = sorted(income_records, key=lambda x: x[5], reverse=True)
    latest_users = []
    seen_names = set()

    for rec in income_records_sorted:
        name = rec[3]
        if name not in seen_names:
            seen_names.add(name)
            latest_users.append(name)
        if len(latest_users) >= 3:
            break

    class_stat_text = "分类统计📟\n"
    for name in latest_users:
        total_rmb = sum(r[1] for r in income_records if r[3] == name)
        total_usd = sum(r[2] for r in income_records if r[3] == name)
        class_stat_text += f"{name} ➡️ {format_number(total_rmb)} = {format_number(total_usd)}U\n"

    # ---------- 今日入款：最新5笔 ----------
    income_records.sort(key=lambda x: x[5], reverse=True)
    income_latest = income_records[:5]
    income_text = f"\n今日入款（{len(income_records)}笔）\n"
    for time_str, rmb, usd, name, rate, _ in income_latest:
        usd_display = rmb / rate if rate else usd
        income_text += f"{time_str}  {format_number(rmb)}/{format_number(rate)}={format_number(usd_display)}  {name}\n"
    if not income_latest:
        income_text += "暂无入款\n"

    # ---------- 今日下发：最新3笔 ----------
    payout_records.sort(key=lambda x: x[4], reverse=True)
    payout_latest = payout_records[:3]
    payout_text = f"\n今日下发（{len(payout_records)}笔）\n"
    for time_str, rmb, usd, name, _ in payout_latest:
        payout_text += f"{time_str}  {format_number(rmb)}/{format_number(rate_fixed)}={format_number(usd)}  {name}\n"
    if not payout_latest:
        payout_text += "暂无下发\n"

    # ---------- 总计 ----------
    total_income_rmb = sum(r[1] for r in income_records)
    total_income_usd = sum(r[2] for r in income_records)
    total_payout_rmb = sum(r[1] for r in payout_records)
    total_payout_usd = sum(r[2] for r in payout_records)
    net_rmb = total_income_rmb - total_payout_rmb
    net_usd = total_income_usd - total_payout_usd

    bill_text = f"""{class_stat_text}{income_text}{payout_text}
总入款金额：{format_number(total_income_rmb)}
费率：{format_number(fee)}%
固定汇率：{format_number(rate_fixed)}

应下发：{format_number(total_income_rmb)} | {format_number(total_income_usd)}U
已下发：{format_number(total_payout_rmb)} | {format_number(total_payout_usd)}U
余额：{format_number(net_rmb)} | {format_number(net_usd)}U
"""

    # ---------- 底部按钮 ----------
    keyboard = [
        [InlineKeyboardButton("TRX闪兑", url="https://t.me/YeMengvip_Bot")],
        [InlineKeyboardButton("完整账单", url=f"https://bot.ym2017.club/bill/{chat_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    return bill_text, reply_markup
