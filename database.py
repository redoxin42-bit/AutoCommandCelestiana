import aiosqlite

DB_PATH = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                target_chat_id INTEGER,
                phone TEXT,
                api_id INTEGER,
                api_hash TEXT,
                farm_mode TEXT DEFAULT 'manual', -- 'manual' или 'auto'
                selected_command TEXT,
                is_running INTEGER DEFAULT 0
            )
        ''')
        await db.commit()

async def get_settings(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_settings(user_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        for key, value in kwargs.items():
            await db.execute(f'''
                INSERT INTO settings (user_id, {key}) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET {key} = ?
            ''', (user_id, value, value))
        await db.commit()
