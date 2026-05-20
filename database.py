import aiosqlite
from config import DB_NAME

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                api_id INTEGER,
                api_hash TEXT,
                session_string TEXT,
                cooldown INTEGER DEFAULT 60,
                command TEXT DEFAULT '.фарм',
                monitoring INTEGER DEFAULT 0,
                chat_id INTEGER,
                is_farming INTEGER DEFAULT 0
            )
        ''')
        await db.commit()

async def save_account(user_id, phone, api_id, api_hash, session_string):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO accounts (user_id, phone, api_id, api_hash, session_string)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, phone, api_id, api_hash, session_string))
        await db.commit()

async def get_account(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT * FROM accounts WHERE user_id = ?', (user_id,)) as cursor:
            return await cursor.fetchone()

async def get_all_accounts():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT * FROM accounts WHERE session_string IS NOT NULL') as cursor:
            return await cursor.fetchall()

async def update_settings(user_id, **kwargs):
    async with aiosqlite.connect(DB_NAME) as db:
        keys = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        await db.execute(f'UPDATE accounts SET {keys} WHERE user_id = ?', values)
        await db.commit()
