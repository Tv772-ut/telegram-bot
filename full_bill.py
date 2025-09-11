from flask import Flask, render_template
from db import get_records, get_group_config
from datetime import datetime
import pytz
import os

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))

def format_time(dt):
    """格式化时间：显示 年-月-日 时:分:秒"""
    if isinstance(dt, str):
        return dt
    elif isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)

def format_number(num):
    """整数显示整数，小数最多两位"""
    if num is None:
        return "0"
    if num == int(num):
        return str(int(num))
    else:
        return f"{num:.2f}"

@app.route("/")
def index():
    return "Flask server is running!"

@app.route("/bill/<chat_id>")
def bill(chat_id):
    try:
        chat_id = int(chat_id)
    except ValueError:
        return "Invalid chat_id", 400

    records = get_records(chat_id)
    group_conf = get_group_config(chat_id)
    rate_fixed = group_conf.get('rate', 1)
    
    # 格式化记录
    formatted_records = []
    for r in records:
        r_type, user, display_name, amount_rmb, amount_usd, rate, operator, time_str = r
        formatted_records.append({
            "type": r_type,
            "user": display_name,
            "rmb": float(amount_rmb),
            "usd": float(amount_usd),
            "rate": float(rate),
            "operator": operator,
            "time": format_time(time_str)
        })

    # 入款汇总 / 下发汇总
    income_summary_dict = {}
    payout_summary_dict = {}

    total_income_rmb = 0
    total_income_usd = 0
    total_payout_rmb = 0
    total_payout_usd = 0

    for r in formatted_records:
        if r['type'] == '入款':
            total_income_rmb += r['rmb']
            total_income_usd += r['usd']
            key = (r['user'], r['operator'])
            if key not in income_summary_dict:
                income_summary_dict[key] = {"total_rmb": 0, "remaining_rmb": 0, "count": 0, "user": r['user'], "operator": r['operator']}
            income_summary_dict[key]["total_rmb"] += r['rmb']
            income_summary_dict[key]["remaining_rmb"] += r['usd']
            income_summary_dict[key]["count"] += 1
        elif r['type'] == '下发':
            total_payout_rmb += r['rmb']
            total_payout_usd += r['usd']
            key = (r['user'], r['operator'])
            if key not in payout_summary_dict:
                payout_summary_dict[key] = {"total_rmb": 0, "remaining_rmb": 0, "count": 0, "user": r['user'], "operator": r['operator']}
            payout_summary_dict[key]["total_rmb"] += r['rmb']
            payout_summary_dict[key]["remaining_rmb"] += r['usd']
            payout_summary_dict[key]["count"] += 1

    # 转换成列表
    income_summary = list(income_summary_dict.values())
    payout_summary = list(payout_summary_dict.values())

    return render_template(
        "bill.html",
        records=formatted_records,
        income_summary=income_summary,
        payout_summary=payout_summary,
        total_income_rmb=format_number(total_income_rmb),
        total_income_usd=format_number(total_income_usd),
        total_payout_rmb=format_number(total_payout_rmb),
        total_payout_usd=format_number(total_payout_usd)
    )

def run_flask():
    app.run(host="0.0.0.0", port=8000, debug=False)

if __name__ == "__main__":
    run_flask()
