import asyncio
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN
from database import init_db, save_account, get_account, get_all_accounts, update_settings

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

temp_clients = {}
active_clients = {}
client_tasks = {}

class LoginStates(StatesGroup):
    waiting_for_credentials = State()
    waiting_for_code = State()
    waiting_for_password = State()

# --- Фоновые циклы для автофарма и мониторинга ---
async def farm_loop(user_id, client):
    while True:
        try:
            acc = await get_account(user_id)
            if not acc or not acc[4]: 
                break
            
            is_farming = acc[9]
            chat_id = acc[8]
            cooldown = acc[5]
            command = acc[6]
            
            if is_farming and chat_id:
                await client.send_message(chat_id, command)
                await asyncio.sleep(cooldown)
            else:
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(5)

async def monitoring_loop(user_id, client):
    while True:
        try:
            acc = await get_account(user_id)
            if not acc or not acc[4]:
                break
            
            monitoring = acc[7]
            chat_id = acc[8]
            
            if monitoring and chat_id:
                await client.send_message(chat_id, ".отн поцеловать")
                await asyncio.sleep(25 * 60)  # 25 минут
            else:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(5)

# --- Динамический запуск юзербота ---
async def start_userbot(user_id, session_string, api_id, api_hash):
    from pyrogram import Client, filters
    
    client = Client(
        name=f"session_{user_id}",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=True
    )
    
    @client.on_message(filters.me & filters.text)
    async def userbot_handler(cl, msg):
        text = msg.text.strip()
        
        if text.startswith('.main'):
            await msg.delete()
            await update_settings(user_id, chat_id=msg.chat.id)
            bot_info = await bot.get_me()
            try:
                res = await cl.get_inline_bot_results(bot_info.username, "menu")
                if res and res.results:
                    await cl.send_inline_bot_result(msg.chat.id, res.query_id, res.results[0].id)
            except Exception as e:
                await cl.send_message(msg.chat.id, f"❌ Включи Inline Mode в @BotFather для бота!\nОшибка: {e}")
                
        elif text.startswith('.cooldown '):
            try:
                cd = int(text.split()[1])
                await update_settings(user_id, cooldown=cd)
                await msg.reply_text(f"✅ КД успешно изменено на {cd} сек.")
            except:
                await msg.reply_text("❌ Формат: `.cooldown [секунды]`")
                
        elif text.startswith('.command '):
            try:
                cmd = text.split(maxsplit=1)[1]
                await update_settings(user_id, command=cmd)
                await msg.reply_text(f"✅ Команда изменена на: `{cmd}`")
            except:
                await msg.reply_text("❌ Формат: `.command [текст команды]`")
                
        elif text.startswith('.monitoring'):
            acc = await get_account(user_id)
            new_st = 1 if not acc[7] else 0
            await update_settings(user_id, monitoring=new_st)
            await msg.reply_text(f"🔄 Мониторинг (.отн поцеловать): {'ВКЛ' if new_st else 'ВЫКЛ'}")

    await client.start()
    active_clients[user_id] = client
    
    t1 = asyncio.create_task(farm_loop(user_id, client))
    t2 = asyncio.create_task(monitoring_loop(user_id, client))
    client_tasks[user_id] = [t1, t2]

# --- Aiogram Хендлеры ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await message.answer(
        "👋 **Привет! Подключим твой аккаунт Telegram.**\n\n"
        "Отправь данные одной строкой через пробел в формате:\n"
        "`номер_телефона api_id api_hash`\n\n"
        "Пример:\n`79991112233 1234567 abcdef1234567890` (без знака +)",
        parse_mode="Markdown"
    )
    await state.set_state(LoginStates.waiting_for_credentials)

@dp.message(LoginStates.waiting_for_credentials)
async def process_credentials(message: types.Message, state: FSMContext):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("❌ Неверный формат. Введи: `номер api_id api_hash`")
        
        phone, api_id, api_hash = parts[0], int(parts[1]), parts[2]
        await state.update_data(phone=phone, api_id=api_id, api_hash=api_hash)
        
        from pyrogram import Client
        client = Client(f"temp_{message.from_user.id}", api_id=api_id, api_hash=api_hash, in_memory=True)
        await client.connect()
        
        code_hash = await client.send_code(phone)
        temp_clients[message.from_user.id] = {"client": client, "code_hash": code_hash.phone_code_hash}
        
        await message.answer("📩 Код авторизации отправлен. Введи его сюда:")
        await state.set_state(LoginStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода: {e}\nНачни заново через /start")
        await state.clear()

@dp.message(LoginStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in temp_clients:
        return await message.answer("Сессия устарела. Напиши /start")
        
    code = message.text.strip()
    data = await state.get_data()
    client = temp_clients[user_id]["client"]
    code_hash = temp_clients[user_id]["code_hash"]
    
    from pyrogram.errors import SessionPasswordNeeded
    try:
        await client.sign_in(data["phone"], code_hash, code)
        session_str = await client.export_session_string()
        await save_account(user_id, data["phone"], data["api_id"], data["api_hash"], session_str)
        
        await message.answer("🎉 Успешный вход! Юзербот запущен. Теперь в любом чате пиши `.main`")
        await start_userbot(user_id, session_str, data["api_id"], data["api_hash"])
        
        await client.disconnect()
        temp_clients.pop(user_id, None)
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer("🔐 На аккаунте обнаружен 2FA пароль. Введи его:")
        await state.set_state(LoginStates.waiting_for_password)
    except Exception as e:
        await message.answer(f"❌ Ошибка авторизации: {e}")
        await client.disconnect()
        temp_clients.pop(user_id, None)
        await state.clear()

@dp.message(LoginStates.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in temp_clients:
        return await message.answer("Сессия устарела. Напиши /start")
        
    password = message.text.strip().replace(" ", "")  # Обработка "4 4 4 4" -> "4444"
    data = await state.get_data()
    client = temp_clients[user_id]["client"]
    
    try:
        await client.check_password(password)
        session_str = await client.export_session_string()
        await save_account(user_id, data["phone"], data["api_id"], data["api_hash"], session_str)
        
        await message.answer("🎉 Успешный вход (с 2FA)! Автофарм готов к работе.")
        await start_userbot(user_id, session_str, data["api_id"], data["api_hash"])
        
        await client.disconnect()
        temp_clients.pop(user_id, None)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Неверный пароль или ошибка: {e}\nНачни заново через /start")
        await client.disconnect()
        temp_clients.pop(user_id, None)
        await state.clear()

# --- Логика обработки Inline-меню ---
def generate_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ Старт Фарм", callback_data="farm_start"),
            InlineKeyboardButton(text="⏸ Стоп Фарм", callback_data="farm_stop")
        ],
        [
            InlineKeyboardButton(text="💕 Мониторинг (Вкл/Выкл)", callback_data="toggle_monitor")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить статус", callback_data="refresh_menu")
        ]
    ])

async def build_menu_text(user_id):
    acc = await get_account(user_id)
    if not acc:
        return "Аккаунт не зарегистрирован в боте."
    cooldown = acc[5]
    command = acc[6]
    monitoring = "ВКЛ" if acc[7] else "ВЫКЛ"
    is_farming = "АКТИВЕН" if acc[9] else "НА ПАУЗЕ"
    
    return (
        f"📊 **Menu Autofarm**\n\n"
        f"⏱ **КД фарма:** {cooldown} сек.\n"
        f"💬 **Команда отправки:** `{command}`\n"
        f"💕 **Мониторинг:** {monitoring} (каждые 25 мин)\n"
        f"⚡ **Статус автофарма:** __{is_farming}__\n\n"
        f"⚙️ Используй кнопки ниже или команды `.cooldown`, `.command`, `.monitoring`"
    )

@dp.inline_query()
async def inline_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    text = await build_menu_text(user_id)
    
    results = [
        InlineQueryResultArticle(
            id="menu",
            title="Menu Autofarm",
            input_message_content=InputTextMessageContent(message_text=text, parse_mode="Markdown"),
            reply_markup=generate_menu_keyboard()
        )
    ]
    await inline_query.answer(results, cache_time=1, is_personal=True)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    acc = await get_account(user_id)
    if not acc:
        return await callback.answer("Аккаунт не найден.", show_alert=True)
        
    action = callback.data
    if action == "farm_start":
        await update_settings(user_id, is_farming=1)
        await callback.answer("Автофарм запущен!")
    elif action == "farm_stop":
        await update_settings(user_id, is_farming=0)
        await callback.answer("Автофарм приостановлен.")
    elif action == "toggle_monitor":
        new_status = 1 if not acc[7] else 0
        await update_settings(user_id, monitoring=new_status)
        await callback.answer(f"Мониторинг: {'ВКЛ' if new_status else 'ВЫКЛ'}")
    elif action == "refresh_menu":
        await callback.answer("Статус обновлен!")
        
    new_text = await build_menu_text(user_id)
    try:
        await callback.message.edit_text(new_text, reply_markup=generate_menu_keyboard(), parse_mode="Markdown")
    except:
        pass

# --- Восстановление сессий при перезапуске бота ---
async def on_startup_restore():
    await init_db()
    accounts = await get_all_accounts()
    for acc in accounts:
        uid, phone, api_id, api_hash, session_str = acc[0], acc[1], acc[2], acc[3], acc[4]
        try:
            await start_userbot(uid, session_str, api_id, api_hash)
            print(f" Юзербот для {uid} успешно перезапущен")
        except Exception as e:
            print(f" Не удалось восстановить сессию {uid}: {e}")

async def main():
    await on_startup_restore()
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
