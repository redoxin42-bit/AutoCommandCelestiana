import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid

import database as db
import parser

# Инициализация конфигурации
BOT_TOKEN = "8674930038:AAFKaZuSsn9f85-cmWopcvQL5Hv_GQipWFw"
API_ID = int(os.getenv("API_ID", 12345)) # Замени или укажи в .env
API_HASH = os.getenv("API_HASH", "your_api_hash")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
userbot_clients = {} # Храним запущенные сессии pyrogram {user_id: Client}

class AuthStates(StatesGroup):
    GET_API = State()
    GET_PHONE = State()
    GET_CODE = State()
    GET_CHAT = State()

# --- ЛОГИКА АВТОМАТИЗАЦИИ ФАРМА ---
async def farm_loop(user_id: int):
    """Цикл автоматического фарма в фоне"""
    while True:
        settings = await db.get_settings(user_id)
        if not settings or not settings['is_running'] or not settings['target_chat_id']:
            await asyncio.sleep(10)
            continue
            
        client = userbot_clients.get(user_id)
        if not client or not client.is_connected:
            await asyncio.sleep(10)
            continue
            
        try:
            chat_id = settings['target_chat_id']
            # 1. Запрашиваем актуальный список действий
            await client.send_message(chat_id, ".отн действия")
            await asyncio.sleep(4) # Ждем ответа от Celestiana
            
            # Получаем последнее сообщение в чате (надеемся, что это ответ Celestiana)
            async for msg in client.get_chat_history(chat_id, limit=3):
                if msg.text and ("действия" in msg.text or "Премиум" in msg.text):
                    commands, cooldowns = parser.parse_celestiana_message(msg.text)
                    
                    if not commands:
                        continue
                        
                    # Выбираем команду в зависимости от режима
                    cmd_to_run = None
                    if settings['farm_mode'] == 'manual':
                        cmd_to_run = settings['selected_command']
                    else:
                        # Авто-режим: берем случайную из доступных
                        import random
                        cmd_to_run = random.choice(commands)
                    
                    if cmd_to_run and cmd_to_run in cooldowns:
                        cd_seconds = cooldowns[cmd_to_run]
                        # 2. Отправляем команду фарма
                        await client.send_message(chat_id, f".отн {cmd_to_run}")
                        # Отправляем лог пользователю в ЛС бота
                        await bot.send_message(user_id, f"🤖 Выполнено: `.отн {cmd_to_run}`. Засыпаю на {cd_seconds} сек.")
                        await asyncio.sleep(cd_seconds)
                        break
        except Exception as e:
            print(f"Ошибка в цикле фарма: {e}")
            
        await asyncio.sleep(300) # Проверка каждые 5 минут, если что-то пошло не так

# --- ХЕНДЛЕРЫ AIOGRAM ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await db.init_db()
    await message.answer("Привет! Давай настроим управление Celestiana.\nВведите ваш API ID и API HASH через пробел:")
    await state.set_state(AuthStates.GET_API)

@dp.message(AuthStates.GET_API)
async def process_api(message: Message, state: FSMContext):
    try:
        api_id, api_hash = message.text.split()
        await state.update_data(api_id=int(api_id), api_hash=api_hash)
        await message.answer("Отлично. Теперь введите номер телефона аккаунта (в международном формате, например +79991234567):")
        await state.set_state(AuthStates.GET_PHONE)
    except:
        await message.answer("Ошибка ввода. Введите API ID и API HASH через пробел!")

@dp.message(AuthStates.GET_PHONE)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    
    await message.answer("Подключаюсь к Telegram для отправки кода...")
    
    client = Client(f"session_{message.from_user.id}", api_id=data['api_id'], api_hash=data['api_hash'])
    await client.connect()
    
    try:
        code_hash = await client.send_code(phone)
        await state.update_data(phone=phone, code_hash=code_hash.phone_code_hash, client=client)
        userbot_clients[message.from_user.id] = client
        await message.answer("Код отправлен. Введите полученный код подтверждения:")
        await state.set_state(AuthStates.GET_CODE)
    except Exception as e:
        await message.answer(f"Ошибка отправки кода: {e}")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.GET_CODE)
async def process_code(message: Message, state: FSMContext):
    data = await state.get_data()
    client = data['client']
    code = message.text.strip()
    
    try:
        await client.sign_in(data['phone'], data['code_hash'], code)
        await message.answer("Авторизация юзербота успешна!\nПришлите ID чата (или username группы), где идет игра с Celestiana:")
        await state.set_state(AuthStates.GET_CHAT)
    except PhoneCodeInvalid:
        await message.answer("Неверный код. Попробуйте еще раз:")
    except SessionPasswordNeeded:
        await message.answer("На аккаунте стоит двухэтапная аутентификация. Данная демо-версия её не поддерживает. Отключите её временно.")
        await state.clear()

@dp.message(AuthStates.GET_CHAT)
async def process_chat(message: Message, state: FSMContext):
    chat_input = message.text.strip()
    try:
        chat_id = int(chat_input)
    except ValueError:
        chat_id = chat_input # Если юзернейм строки
        
    await db.update_settings(message.from_user.id, target_chat_id=str(chat_id), is_running=1)
    await state.clear()
    
    # Запускаем фоновую задачу фарма для этого юзера
    asyncio.create_task(farm_loop(message.from_user.id))
    
    await message.answer("Настройка завершена! Бот запущен.\nИспользуйте команду /main для управления режимами.")

@dp.message(F.text == "/main")
async def cmd_main(message: Message):
    settings = await db.get_settings(message.from_user.id)
    if not settings:
        return await message.answer("Сначала пройдите настройку через /start")
        
    kb = [
        [KeyboardButton(text="🔄 Режим: Авто-рандом"), KeyboardButton(text="🎯 Режим: Ручной выбор")],
        [KeyboardButton(text="🛑 Остановить фарм"), KeyboardButton(text="▶️ Запустить фарм")]
    ]
    markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    status = "РАБОТАЕТ" if settings['is_running'] else "ОСТАНОВЛЕН"
    await message.answer(
        f"⚙️ **Панель управления Celestiana**\n\n"
        f"Текущий статус: `{status}`\n"
        f"Режим: `{settings['farm_mode']}`\n"
        f"Выбранная команда: `{settings['selected_command']}`\n\n"
        f"Для ручного выбора команды отправьте её точное название в кавычках (например: `Квантовое слияние`).",
        reply_markup=markup
    )

@dp.message(F.text == "🔄 Режим: Авто-рандом")
async def set_auto(message: Message):
    await db.update_settings(message.from_user.id, farm_mode='auto')
    await message.answer("Установлен автоматический выбор случайной доступной команды.")

@dp.message(F.text == "🎯 Режим: Ручной выбор")
async def set_manual(message: Message):
    await db.update_settings(message.from_user.id, farm_mode='manual')
    await message.answer("Установлен ручной режим. Напишите боту название команды текстом, чтобы зафиксировать её.")

@dp.message(F.text == "🛑 Остановить фарм")
async def stop_farm(message: Message):
    await db.update_settings(message.from_user.id, is_running=0)
    await message.answer("Фарм остановлен.")

@dp.message(F.text == "▶️ Запустить фарм")
async def start_farm(message: Message):
    await db.update_settings(message.from_user.id, is_running=1)
    await message.answer("Фарм возобновлен.")

@dp.message()
async def save_manual_command(message: Message):
    settings = await db.get_settings(message.from_user.id)
    if settings and settings['farm_mode'] == 'manual':
        cmd = message.text.strip()
        await db.update_settings(message.from_user.id, selected_command=cmd)
        await message.answer(f"Принято! Буду фармить команду: `.отн {cmd}`")

async def main():
    await db.init_db()
    # Восстановление фоновых задач для уже авторизованных сессий при перезапуске хоста можно сделать тут
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
