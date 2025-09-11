import pytz
from datetime import datetime

def format_amount(amount: float) -> str:
    if amount is None:
        return "0"
    return str(int(amount)) if amount == int(amount) else f"{amount:.2f}"

def get_beijing_time():
    tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(tz)

def _norm_username(u: str) -> str:
    return (u or "").lstrip("@").lower()
