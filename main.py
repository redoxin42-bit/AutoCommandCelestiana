import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid

import database as db
import parser

# Основной токен твоего управляющего бота
BOT_TOKEN = "8674930038:AAFKaZuSsn9f85-cmWopcvQL5Hv_GQipWFw"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
userbot_clients = {}  # Храним активные сессии юзерботов в памяти: {user_id: Client}

class AuthStates(StatesGroup):
    GET_API = State()
    GET_PHONE = State()
    GET_CODE = State()
    GET_CHAT = State()

# --- ЛОГИКА АВТОМАТИЗАЦИИ ФАРМА ---
async def farm_loop(user_id: int):
    """Цикл автоматического фарма в фоне для конкретного пользователя"""
    print(f"🚀 Запущен фоновый фарм для пользователя {user_id}")
    while True:
        settings = await db.get_settings(user_id)
        # Если фарм отключен или не настроен чат — отдыхаем
        if not settings or not settings['is_running'] or not settings['target_chat_id']:
            await asyncio.sleep(10)
            continue
            
        client = userbot_clients.get(user_id)
        if not client or not client.is_connected:
            await asyncio.sleep(10)
            continue
            
        try:
            chat_id = settings['target_chat_id']
            # Проверяем, если строка состоит из цифр, делаем int (для ID чатов)
            if str(chat_id).replace('-', '').isdigit():
                chat_id = int(chat_id)

            # 1. Запрашиваем актуальный список действий
            await client.send_message(chat_id, ".отн действия")
            await asyncio.sleep(4)  # Ждем, пока Celestiana ответит
            
            # Получаем последние сообщения, ищем ответ от Celestiana
            async for msg in client.get_chat_history(chat_id, limit=3):
                if msg.text and ("действия" in msg.text or "Премиум" in msg.text):
                    commands, cooldowns = parser.parse_celestiana_message(msg.text)
                    
                    if not commands:
                        continue
                        
                    # Выбираем команду (ручной режим или авто-рандом)
                    cmd_to_run = None
                    if settings['farm_mode'] == 'manual':
                        cmd_to_run = settings['selected_command']
                    else:
                        import random
                        cmd_to_run = random.choice(commands)
                    
                    if cmd_to_run and cmd_to_run in cooldowns:
                        cd_seconds = cooldowns[cmd_to_run]
                        # 2. Отправляем команду фарма в чат
                        await client.send_message(chat_id, f".отн {cmd_to_run}")
                        
                        # Отправляем лог пользователю в ЛС управляющего бота
                        try:
                            await bot.send_message(
                                user_id, 
                                f"🤖 **Действие выполнено:** `.отн {cmd_to_run}`\n"
                                f"⏳ Пауза по КД: `{cd_seconds // 60}м. {cd_seconds % 60}с.`"
                            )
                        except Exception:
                            pass  # Если юзер заблокировал бота
                            
                        await asyncio.sleep(cd_seconds)
                        break
        except Exception as e:
            print(f"Ошибка в цикле фарма у юзера {user_id}: {e}")
            
        await asyncio.sleep(300)  # Стандартный цикл проверки (5 минут), если команда не отправилась

# --- ВОССТАНОВЛЕНИЕ СЕССИЙ ПРИ ПЕРЕЗАПУСКЕ БОТА ---
async def restore_all_sessions():
    """Поднимает всех активных юзерботов из базы данных при перезапуске скрипта"""
    await db.init_db()
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM settings WHERE is_running = 1") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                user_id = row['user_id']
                # Проверяем, существует ли файл сессии для этого юзера
                if os.path.exists(f"session_{user_id}.session") and row['api_id'] and row['api_hash']:
                    print(f"Включаю юзербота для игрока {user_id}...")
                    try:
                        client = Client(f"session_{user_id}", api_id=row['api_id'], api_hash=row['api_hash'])
                        await client.connect()
                        userbot_clients[user_id] = client
                        asyncio.create_task(farm_loop(user_id))
                    except Exception as e:
                        print(f"Не удалось восстановить сессию {user_id}: {e}")

# --- ХЕНДЛЕРЫ AIOGRAM ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await db.init_db()
    await message.answer(
        "👋 Привет! Этот бот поможет тебе автоматизировать действия в Celestiana.\n\n"
        "Для начала настройки введи свой **API ID** и **API HASH** через пробел.\n"
        "_(Получить их можно на сайте my.telegram.org)_"
    )
    await state.set_state(AuthStates.GET_API)

@dp.message(AuthStates.GET_API)
async def process_api(message: Message, state: FSMContext):
    try:
        api_id, api_hash = message.text.split()
        await state.update_data(api_id=int(api_id), api_hash=api_hash)
        await message.answer("Получено! Теперь введи номер телефона от этого аккаунта (например, +79991234567):")
        await state.set_state(AuthStates.GET_PHONE)
    except ValueError:
        await message.answer("❌ Неверный формат. Введи API ID (цифры) и API HASH через пробел в одном сообщении!")

@dp.message(AuthStates.GET_PHONE)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    
    await message.answer("🔄 Подключаюсь к Telegram для отправки кода подтверждения...")
    
    client = Client(f"session_{message.from_user.id}", api_id=data['api_id'], api_hash=data['api_hash'])
    try:
        await client.connect()
        code_hash = await client.send_code(phone)
        await state.update_data(phone=phone, code_hash=code_hash.phone_code_hash, client=client)
        userbot_clients[message.from_user.id] = client
        await message.answer("📩 Код подтверждения отправлен в твой Telegram. Введи его сюда:")
        await state.set_state(AuthStates.GET_CODE)
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода: {e}\nПопробуй заново через /start")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.GET_CODE)
async def process_code(message: Message, state: FSMContext):
    data = await state.get_data()
    client = data['client']
    code = message.text.strip().replace(" ", "")  # Убираем пробелы, если юзер скопировал "123 45"
    
    try:
        await client.sign_in(data['phone'], data['code_hash'], code)
        await message.answer("✅ Авторизация успешна!\nТеперь отправь мне ID чата (или username группы), где вы играете в Celestiana:")
        await state.set_state(AuthStates.GET_CHAT)
    except PhoneCodeInvalid:
        await message.answer("❌ Неверный код. Попробуй ввести еще раз:")
    except SessionPasswordNeeded:
        await message.answer("🔒 На аккаунте стоит двухэтапный пароль (2FA). Пожалуйста, временно отключи его в настройках Telegram и начни настройку заново через /start.")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.GET_CHAT)
async def process_chat(message: Message, state: FSMContext):
    chat_input = message.text.strip()
    data = await state.get_data()
    
    # Сохраняем ВСЕ данные пользователя в БД, включая его личные API_ID и API_HASH
    await db.update_settings(
        message.from_user.id, 
        target_chat_id=chat_input, 
        phone=data['phone'],
        api_id=data['api_id'],
        api_hash=data['api_hash'],
        is_running=1
    )
    await state.clear()
    
    # Запускаем персональный фоновый процесс для этого пользователя
    asyncio.create_task(farm_loop(message.from_user.id))
    
    await message.answer("🎉 Настройка полностью завершена! Бот включен.\nИспользуй команду /main для переключения режимов.")

@dp.message(F.text == "/main")
async def cmd_main(message: Message):
    settings = await db.get_settings(message.from_user.id)
    if not settings:
        return await message.answer("Ты еще не настроил бота. Напиши /start")
        
    kb = [
        [KeyboardButton(text="🔄 Режим: Авто-рандом"), KeyboardButton(text="🎯 Режим: Ручной выбор")],
        [KeyboardButton(text="🛑 Остановить фарм"), KeyboardButton(text="▶️ Запустить фарм")]
    ]
    markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    status = "🟢 РАБОТАЕТ" if settings['is_running'] else "🔴 ОСТАНОВЛЕН"
    await message.answer(
        f"⚙️ **Панель управления Celestiana**\n\n"
        f"Статус авто-фарма: `{status}`\n"
        f"Режим выбора команд: `{settings['farm_mode']}`\n"
        f"Выбранное действие: `{settings['selected_command'] or 'Не выбрано'}`\n\n"
        f"💡 Если включен ручной режим, просто пришли мне точное название действия текстом (например: `Квантовое слияние`), чтобы бот спамил именно его.",
        reply_markup=markup
    )

@dp.message(F.text == "🔄 Режим: Авто-рандом")
async def set_auto(message: Message):
    await db.update_settings(message.from_user.id, farm_mode='auto')
    await message.answer("🤖 Режим изменен. Бот будет сам выбирать случайную доступную команду из списка.")

@dp.message(F.text == "🎯 Режим: Ручной выбор")
async def set_manual(message: Message):
    await db.update_settings(message.from_user.id, farm_mode='manual')
    await message.answer("🎯 Режим изменен. Напиши мне название команды текстом, чтобы зафиксировать её.")

@dp.message(F.text == "🛑 Остановить фарм")
async def stop_farm(message: Message):
    await db.update_settings(message.from_user.id, is_running=0)
    await message.answer("⏸️ Фарм успешно остановлен.")

@dp.message(F.text == "▶️ Запустить фарм")
async def start_farm(message: Message):
    await db.update_settings(message.from_user.id, is_running=1)
    await message.answer("▶️ Фарм возобновлен.")

@dp.message()
async def save_manual_command(message: Message):
    settings = await db.get_settings(message.from_user.id)
    if settings and settings['farm_mode'] == 'manual':
        cmd = message.text.strip().replace("«", "").replace("»", "")
        await db.update_settings(message.from_user.id, selected_command=cmd)
        await message.answer(f"✅ Команда сохранена! Буду циклично отправлять: `.отн {cmd}`")

async def main():
    # При старте скрипта автоматически восстанавливаем сессии всех, у кого был включен фарм
    await restore_all_sessions()
    print("🤖 Основной управляющий бот запущен и слушает команды...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
