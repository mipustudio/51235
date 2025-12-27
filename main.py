import asyncio
import aiohttp
from datetime import datetime
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InputFile, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import config, logger
from database import db

# Импорты для обработки изображений
try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL не установлен. Обработка фото будет недоступна.")

# Импорт для GigaChat
try:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False
    logger.warning("GigaChat не установлен. Генерация постов будет недоступна.")

# ========== STATES (FSM) ==========
class PostStates(StatesGroup):
    waiting_for_topic = State()
    waiting_for_style = State()

class EventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_date = State()

class MediaStates(StatesGroup):
    waiting_for_search = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
TOKEN = config.TOKEN
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Инициализация GigaChat если доступен
gigachat_client = None
if GIGACHAT_AVAILABLE and config.GIGACHAT_CLIENT_ID and config.GIGACHAT_SECRET:
    try:
        gigachat_client = GigaChat(
            credentials=config.GIGACHAT_SECRET,
            scope=config.GIGACHAT_CLIENT_ID,
            verify_ssl_certs=False
        )
        logger.info("GigaChat клиент инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации GigaChat: {e}")
        gigachat_client = None

# ========== MIDDLEWARE & ДОСТУП ==========
# Правильная сигнатура для middleware в aiogram 3.x
async def check_access_middleware(handler, event: Message, data: dict):
    """Проверка доступа пользователя"""
    if event.from_user:
        username = event.from_user.username or str(event.from_user.id)
        
        # Админы всегда имеют доступ
        if event.from_user.id in config.ADMIN_IDS:
            return await handler(event, data)
        
        # Проверка whitelist
        if db.is_whitelisted(username):
            return await handler(event, data)
        else:
            await event.answer("⛔ У вас нет доступа к боту. Обратитесь к администратору.")
            return
    
    return await handler(event, data)

# Регистрируем middleware
dp.message.middleware.register(check_access_middleware)

# ========== КОМАНДЫ АДМИНИСТРАТОРА ==========
@dp.message(Command("add"))
async def add_to_whitelist(message: Message):
    """Добавление пользователя в whitelist (только для админов)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Эта команда только для администраторов!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /add user @username")
        return
    
    username = args[2].replace("@", "")
    if db.add_to_whitelist(username):
        await message.answer(f"✅ Пользователь @{username} добавлен в whitelist!")
    else:
        await message.answer(f"ℹ️ Пользователь @{username} уже в whitelist.")

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ-панель с inline кнопками"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    keyboard = [
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📝 Управление событиями", callback_data="admin_events")],
        [types.InlineKeyboardButton(text="🏢 Управление СМИ", callback_data="admin_media")],
        [types.InlineKeyboardButton(text="🔄 Перезапуск бота", callback_data="admin_restart")],
    ]
    
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("👑 Админ-панель:", reply_markup=markup)

# ========== ОБРАБОТКА ФОТО С ЛОГОТИПОМ ==========
@dp.message(F.photo)
async def process_photo(message: Message):
    """Обработка фото с добавлением логотипа и фильтров"""
    if not PIL_AVAILABLE:
        await message.answer("❌ Обработка фото временно недоступна (PIL не установлен)")
        return
    
    try:
        await message.answer("🔄 Обрабатываю фото...")
        
        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path
        
        # Загружаем фото
        photo_bytes = await bot.download_file(file_path)
        image = Image.open(BytesIO(photo_bytes.read()))
        
        # Применяем фильтры
        image = image.filter(ImageFilter.SHARPEN)
        
        # Добавляем текст (простой логотип)
        draw = ImageDraw.Draw(image)
        # Простой текст в качестве примера
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except:
            font = ImageFont.load_default()
        
        # Добавляем текст в правый нижний угол
        text = "Saratov"
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        x = image.width - text_width - 20
        y = image.height - text_height - 20
        
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 128))
        
        # Сохраняем результат
        output = BytesIO()
        image.save(output, format='JPEG', quality=95)
        output.seek(0)
        
        # Отправляем обработанное фото
        await message.answer_photo(
            types.BufferedInputFile(output.getvalue(), filename="processed.jpg"),
            caption="✅ Фото обработано с добавлением логотипа!"
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await message.answer("❌ Ошибка при обработке фото")

# ========== ГЕНЕРАЦИЯ ПОСТОВ ЧЕРЕЗ GIGACHAT ==========
@dp.message(Command("generate_post"))
async def start_post_generation(message: Message, state: FSMContext):
    """Начало генерации поста через AI"""
    if not GIGACHAT_AVAILABLE or gigachat_client is None:
        await message.answer("❌ Генерация постов временно недоступна (GigaChat не настроен)")
        return
    
    await message.answer("📝 Введите тему для поста:")
    await state.set_state(PostStates.waiting_for_topic)

@dp.message(PostStates.waiting_for_topic)
async def process_topic(message: Message, state: FSMContext):
    """Обработка темы и запрос стиля"""
    await state.update_data(topic=message.text)
    
    keyboard = [
        [types.InlineKeyboardButton(text="🎯 Официальный", callback_data="style_official")],
        [types.InlineKeyboardButton(text="😊 Дружеский", callback_data="style_friendly")],
        [types.InlineKeyboardButton(text="🔥 Продающий", callback_data="style_promo")],
        [types.InlineKeyboardButton(text="📰 Новостной", callback_data="style_news")],
    ]
    
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("🎨 Выберите стиль поста:", reply_markup=markup)
    await state.set_state(PostStates.waiting_for_style)

@dp.callback_query(F.data.startswith("style_"))
async def generate_post_with_style(callback: CallbackQuery, state: FSMContext):
    """Генерация поста с выбранным стилем"""
    style = callback.data.replace("style_", "")
    data = await state.get_data()
    topic = data.get("topic", "")
    
    await callback.message.edit_text("🤖 Генерирую пост...")
    
    try:
        # Создаем промпт в зависимости от стиля
        style_prompts = {
            "official": "Напиши официальный пост на тему",
            "friendly": "Напиши дружеский, неформальный пост на тему",
            "promo": "Напиши продающий пост на тему",
            "news": "Напиши новостной пост на тему"
        }
        
        prompt = f"{style_prompts.get(style, 'Напиши пост на тему')}: {topic}. Сделай текст на русском языке."
        
        # Генерируем текст через GigaChat
        response = gigachat_client.chat(
            Chat(messages=[
                Messages(role=MessagesRole.USER, content=prompt)
            ])
        )
        
        post_text = response.choices[0].message.content
        
        # Отправляем результат
        await callback.message.answer(f"📋 Сгенерированный пост ({style}):\n\n{post_text}")
        
    except Exception as e:
        logger.error(f"Ошибка генерации поста: {e}")
        await callback.message.answer("❌ Ошибка при генерации поста")
    
    await state.clear()
    await callback.answer()

# ========== УПРАВЛЕНИЕ МЕРОПРИЯТИЯМИ (CRUD) ==========
@dp.message(Command("events"))
async def show_events(message: Message):
    """Показать все мероприятия"""
    events = db.get_events()
    
    if not events:
        await message.answer("📅 Мероприятий пока нет.")
        return
    
    response = "📅 Список мероприятий:\n\n"
    for event in events[:10]:
        response += f"• {event.get('title', 'Без названия')} ({event.get('date', 'дата не указана')})\n"
        response += f"  ID: {event.get('id')}\n\n"
    
    await message.answer(response[:4000])  # Ограничение Telegram

@dp.message(Command("add_event"))
async def start_add_event(message: Message, state: FSMContext):
    """Начать добавление мероприятия"""
    await message.answer("📝 Введите название мероприятия:")
    await state.set_state(EventStates.waiting_for_title)

@dp.message(EventStates.waiting_for_title)
async def process_event_title(message: Message, state: FSMContext):
    """Обработка названия мероприятия"""
    await state.update_data(title=message.text)
    await message.answer("📄 Введите описание мероприятия:")
    await state.set_state(EventStates.waiting_for_description)

@dp.message(EventStates.waiting_for_description)
async def process_event_description(message: Message, state: FSMContext):
    """Обработка описания мероприятия"""
    await state.update_data(description=message.text)
    await message.answer("📅 Введите дату мероприятия (в формате ДД.ММ.ГГГГ):")
    await state.set_state(EventStates.waiting_for_date)

@dp.message(EventStates.waiting_for_date)
async def process_event_date(message: Message, state: FSMContext):
    """Обработка даты и сохранение мероприятия"""
    event_data = await state.get_data()
    event_data["date"] = message.text
    event_data["creator"] = message.from_user.username or str(message.from_user.id)
    
    event_id = db.add_event(event_data)
    
    await message.answer(f"✅ Мероприятие добавлено! ID: {event_id}")
    await state.clear()

@dp.message(Command("delete_event"))
async def delete_event_command(message: Message):
    """Удаление мероприятия"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /delete_event <id_мероприятия>")
        return
    
    event_id = args[1]
    if db.delete_event(event_id):
        await message.answer(f"✅ Мероприятие {event_id} удалено!")
    else:
        await message.answer(f"❌ Мероприятие с ID {event_id} не найдено.")

# ========== БАЗА СМИ САРАТОВА ==========
@dp.message(Command("media"))
async def media_search(message: Message, state: FSMContext):
    """Поиск в базе СМИ Саратова"""
    await message.answer("🔍 Введите запрос для поиска СМИ:")
    await state.set_state(MediaStates.waiting_for_search)

@dp.message(MediaStates.waiting_for_search)
async def process_media_search(message: Message, state: FSMContext):
    """Обработка поискового запроса"""
    query = message.text
    results = db.search_media(query)
    
    if not results:
        await message.answer("🔍 По вашему запросу ничего не найдено.")
        await state.clear()
        return
    
    response = f"📰 Найдено СМИ по запросу '{query}':\n\n"
    for media in results[:5]:
        response += f"• {media.get('name', 'Неизвестно')}\n"
        if media.get('description'):
            response += f"  {media.get('description')[:50]}...\n"
        response += "\n"
    
    await message.answer(response)
    await state.clear()

@dp.message(Command("add_media"))
async def add_media_command(message: Message):
    """Добавление СМИ в базу (только для админов)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Эта команда только для администраторов!")
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /add_media <название> <описание>")
        return
    
    media_data = {
        "name": args[1],
        "description": args[2],
        "added_by": message.from_user.username or str(message.from_user.id),
        "added_at": datetime.now().isoformat()
    }
    
    db.add_media(media_data)
    await message.answer(f"✅ СМИ '{args[1]}' добавлено в базу!")

# ========== КОМАНДА ПЕРЕЗАПУСКА ДЛЯ BOTHOST ==========
@dp.message(Command("restart_bot"))
async def restart_bot_command(message: Message):
    """Перезапуск бота через API Bothost (только для админов)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Эта команда только для администраторов!")
        return
    
    if not config.BOT_ID:
        await message.answer("❌ BOT_ID не найден в переменных окружения")
        return
    
    await message.answer("🔄 Отправляю запрос на перезапуск...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{config.get_agent_url()}/api/bots/self/restart",
                headers={'X-Bot-ID': config.BOT_ID},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()
                
                if result.get('ok'):
                    await message.answer(f"✅ {result.get('message', 'Бот перезапущен')}")
                else:
                    await message.answer(f"❌ Ошибка: {result.get('msg', 'Неизвестная ошибка')}")
    except Exception as e:
        logger.error(f"Ошибка перезапуска через Bothost API: {e}")
        await message.answer(f"❌ Ошибка подключения к API Bothost: {str(e)}")

# ========== ОБРАБОТКА CALLBACK-QUERY ДЛЯ АДМИН-ПАНЕЛИ ==========
@dp.callback_query(F.data.startswith("admin_"))
async def handle_admin_actions(callback: CallbackQuery):
    """Обработка действий из админ-панели"""
    action = callback.data
    
    if action == "admin_stats":
        events_count = len(db.get_events())
        media_count = len(db.search_media(""))
        await callback.message.answer(f"📊 Статистика:\n• Мероприятий: {events_count}\n• СМИ в базе: {media_count}")
        
    elif action == "admin_events":
        events = db.get_events()
        if events:
            response = "📅 Последние мероприятия:\n\n"
            for event in events[-5:]:
                response += f"• {event.get('title')} (ID: {event.get('id')})\n"
                response += f"  Дата: {event.get('date', 'не указана')}\n\n"
            await callback.message.answer(response)
        else:
            await callback.message.answer("📅 Мероприятий пока нет.")
    
    elif action == "admin_media":
        await callback.message.answer("🏢 Управление СМИ:\n\n"
                                     "/add_media <название> <описание> - добавить СМИ\n"
                                     "/media - поиск СМИ\n\n"
                                     "Пример: /add_media \"Саратов Сегодня\" \"Новостной портал города Саратова\"")
    
    elif action == "admin_restart":
        keyboard = [[
            types.InlineKeyboardButton(text="✅ Да, перезапустить", callback_data="confirm_restart"),
            types.InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_restart")
        ]]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        await callback.message.answer("⚠️ Вы уверены, что хотите перезапустить бота?", reply_markup=markup)
    
    await callback.answer()

@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart(callback: CallbackQuery):
    """Подтверждение перезапуска бота"""
    await restart_bot_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart(callback: CallbackQuery):
    """Отмена перезапуска"""
    await callback.message.edit_text("❌ Перезапуск отменен.")
    await callback.answer()

# ========== СТАРТОВАЯ КОМАНДА И ПОМОЩЬ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    """Обработка команды /start"""
    username = message.from_user.username or str(message.from_user.id)
    
    if message.from_user.id in config.ADMIN_IDS:
        welcome = "👑 Добро пожаловать, администратор!"
    elif db.is_whitelisted(username):
        welcome = "✅ Добро пожаловать! Ваш доступ подтвержден."
    else:
        welcome = "🔒 У вас нет доступа к боту. Обратитесь к администратору."
    
    await message.answer(
        f"{welcome}\n\n"
        "Доступные команды:\n"
        "• /admin - админ-панель (только для админов)\n"
        "• /add user @username - добавить пользователя\n"
        "• /generate_post - создать пост через AI\n"
        "• /events - список мероприятий\n"
        "• /add_event - добавить мероприятие\n"
        "• /delete_event <id> - удалить мероприятие\n"
        "• /media - поиск в базе СМИ\n"
        "• /add_media - добавить СМИ\n"
        "• /restart_bot - перезапустить бота (админы)\n\n"
        "Просто отправьте фото для обработки!"
    )

@dp.message(Command("help"))
async def help_command(message: Message):
    """Команда помощи"""
    await start_command(message)

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("🤖 Бот запускается...")
    logger.info(f"Bot ID: {config.BOT_ID}")
    logger.info(f"User ID: {config.USER_ID}")
    logger.info(f"Admin IDs: {config.ADMIN_IDS}")
    logger.info(f"Domain: {config.DOMAIN}")
    logger.info(f"Port: {config.PORT}")
    
    # Проверяем доступность модулей
    if not PIL_AVAILABLE:
        logger.warning("PIL не установлен - обработка фото недоступна")
    
    if not GIGACHAT_AVAILABLE or gigachat_client is None:
        logger.warning("GigaChat не настроен - генерация постов недоступна")
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")