import sqlite3
from datetime import datetime
import pytz

# 初始化数据库
def init_db():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    # 创建群组配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_configs (
            chat_id INTEGER PRIMARY KEY,
            rate REAL DEFAULT 7.2,
            fee REAL DEFAULT 0,
            daily_reset_hour INTEGER DEFAULT 0
        )
    ''')
    
    # 创建记账记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounting_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            type TEXT,
            user TEXT,
            display_name TEXT,
            amount_rmb REAL,
            amount_usd REAL,
            rate REAL,
            operator TEXT,
            time TEXT,
            msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES group_configs (chat_id)
        )
    ''')
    
    # 创建操作员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operators (
            chat_id INTEGER,
            username TEXT,
            PRIMARY KEY (chat_id, username),
            FOREIGN KEY (chat_id) REFERENCES group_configs (chat_id)
        )
    ''')
    
    # 创建钱包地址表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet_addresses (
            chat_id INTEGER,
            address TEXT,
            remark TEXT,
            PRIMARY KEY (chat_id, address),
            FOREIGN KEY (chat_id) REFERENCES group_configs (chat_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# 群组配置相关函数
def get_group_config(chat_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT rate, fee, daily_reset_hour FROM group_configs WHERE chat_id = ?", 
        (chat_id,)
    )
    row = cursor.fetchone()
    
    if row:
        result = {"rate": row[0], "fee": row[1], "daily_reset_hour": row[2]}
    else:
        # 创建默认配置
        cursor.execute(
            "INSERT INTO group_configs (chat_id, rate, fee, daily_reset_hour) VALUES (?, ?, ?, ?)",
            (chat_id, 7.2, 0, 0)
        )
        conn.commit()
        result = {"rate": 7.2, "fee": 0, "daily_reset_hour": 0}
    
    conn.close()
    return result

def set_group_rate(chat_id, rate):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR REPLACE INTO group_configs (chat_id, rate) VALUES (?, ?)",
        (chat_id, rate)
    )
    conn.commit()
    conn.close()

def set_group_fee(chat_id, fee):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR REPLACE INTO group_configs (chat_id, fee) VALUES (?, ?)",
        (chat_id, fee)
    )
    conn.commit()
    conn.close()

def set_group_daily_reset(chat_id, hour):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR REPLACE INTO group_configs (chat_id, daily_reset_hour) VALUES (?, ?)",
        (chat_id, hour)
    )
    conn.commit()
    conn.close()

# 记账记录相关函数
def add_record(chat_id, record):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        '''INSERT INTO accounting_records 
        (chat_id, type, user, display_name, amount_rmb, amount_usd, rate, operator, time, msg_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (chat_id, record["type"], record["user"], record["display_name"], 
         record["amount_rmb"], record["amount_usd"], record["rate"], 
         record["operator"], record["time"], record["msg_id"])
    )
    conn.commit()
    conn.close()

def delete_records(chat_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM accounting_records WHERE chat_id = ?",
        (chat_id,)
    )
    conn.commit()
    conn.close()
    return "✅ 所有记账记录已删除"

def remove_record_by_msgid(chat_id, msg_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM accounting_records WHERE chat_id = ? AND msg_id = ?",
        (chat_id, msg_id)
    )
    conn.commit()
    conn.close()
    return "✅ 记录已删除"

def get_records(chat_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT type, user, display_name, amount_rmb, amount_usd, rate, operator, time FROM accounting_records WHERE chat_id = ? ORDER BY created_at",
        (chat_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

# 操作员管理函数
def add_operator(chat_id, username):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR IGNORE INTO operators (chat_id, username) VALUES (?, ?)",
        (chat_id, username)
    )
    conn.commit()
    conn.close()

def remove_operator(chat_id, username):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM operators WHERE chat_id = ? AND username = ?",
        (chat_id, username)
    )
    conn.commit()
    conn.close()

def get_operators(chat_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT username FROM operators WHERE chat_id = ?",
        (chat_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def load_operators():
    # 这个函数主要用于初始化，可以在启动时调用
    pass

# 钱包地址管理函数
def get_wallet_addresses_db(chat_id):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT address, remark FROM wallet_addresses WHERE chat_id = ?",
        (chat_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"address": row[0], "remark": row[1]} for row in rows]

def add_wallet_address_db(chat_id, address, remark):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR REPLACE INTO wallet_addresses (chat_id, address, remark) VALUES (?, ?, ?)",
        (chat_id, address, remark)
    )
    conn.commit()
    conn.close()

def delete_wallet_address_db(chat_id, address):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM wallet_addresses WHERE chat_id = ? AND address = ?",
        (chat_id, address)
    )
    conn.commit()
    conn.close()
    return True

# 获取所有钱包地址（用于 TRON 监听器）
def get_all_wallet_addresses():
    """
    获取所有群组的所有钱包地址
    返回格式: [{'chat_id': 123456, 'address': 'T...', 'remark': '备注'}, ...]
    """
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT chat_id, address, remark FROM wallet_addresses"
    )
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'chat_id': row[0],
            'address': row[1],
            'remark': row[2] or ''
        })
    
    return result
