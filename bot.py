import os
import asyncio
import threading
import logging
from telegram.ext import Application, MessageHandler, filters, CallbackQueryHandler
from handlers.accounting import handle_message
from db import init_db
import config
import full_bill

# 导入 TRON 监听器
from tron_listener import TronListener

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Telegram_Bot")

# ---------- 回调处理 ----------
async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "refresh_bill":
        from report import generate_bill
        chat_id = query.message.chat_id
        bill_text, bill_markup = generate_bill(chat_id)
        await query.edit_message_text(text=bill_text, reply_markup=bill_markup)
    elif query.data == "export_excel":
        await query.edit_message_text(text="✅ Excel导出功能即将实现")

# ---------- 初始化数据库 ----------
async def post_init(application):
    await asyncio.to_thread(init_db)
    application.bot_data["SUPER_ADMIN_IDS"] = config.SUPER_ADMIN_IDS
    
    # 启动 TRON 监听器
    tron_listener = TronListener(application.bot)
    application.bot_data["tron_listener"] = tron_listener
    asyncio.create_task(tron_listener.start_listening())

# ---------- 后台启动 Flask ----------
def start_flask():
    full_bill.run_flask()  # full_bill.py 中定义的 run_flask()

# ---------- 主函数 ----------
def main():
    # 后台线程启动 Flask
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    print("Flask 网页服务已启动，访问 https://bot.ym2017.club/")

    # 创建 Telegram Bot Application
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    
    # 添加消息处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # 添加回调查询处理器
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # 启动 Bot
    print("Bot 正在启动...")
    application.run_polling()

if __name__ == "__main__":
    main()
