import os
from dotenv import load_dotenv

load_dotenv()

# Bot 配置
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_IDS = [int(id) for id in os.getenv("SUPER_ADMIN_IDS", "").split(",") if id]

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
