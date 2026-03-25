import os
import sys
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Any
from io import BytesIO
from collections import defaultdict

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ========== ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ python-dotenv загружен")
except ImportError:
    logger.warning("⚠️ python-dotenv не установлен, используем системные переменные")

# ========== КОНФИГУРАЦИЯ ==========
class Config:
    TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TOKEN')
    if not TOKEN:
        logger.error("❌ Не найден BOT_TOKEN в переменных окружения!")
        raise ValueError("Установите BOT_TOKEN в настройках Bothost")
    
    BOT_ID = os.getenv('BOT_ID', '')
    USER_ID = os.getenv('USER_ID', '')
    GIGACHAT_CLIENT_ID = "019b2405-4854-7d29-9a54-938aa6fff638"
    GIGACHAT_SECRET = "dc515277-136b-41b9-b5e4-dcad944bb94b"
    ADMIN_IDS = [671065514]
    MAX_PHOTOS_PER_BATCH = 10
    
    @staticmethod
    def get_agent_url():
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

config = Config()
logger.info("✅ Конфигурация загружена")

# ========== ХРАНЕНИЕ АЛЬБОМОВ ==========
album_storage = defaultdict(list)

# ========== БАЗА ДАННЫХ (JSON) ==========
class JSONDatabase:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        
        self.whitelist_file = os.path.join(data_dir, "whitelist.json")
        self.events_file = os.path.join(data_dir, "events.json")
        self.media_file = os.path.join(data_dir, "media.json")
        
        self._init_files()
        self.cache = {}
    
    def _init_files(self):
        defaults = {
            self.whitelist_file: {"users": [], "admins": config.ADMIN_IDS},
            self.events_file: {"events": []},
            self.media_file: {"media": []}
        }
        
        for file, default_data in defaults.items():
            if not os.path.exists(file):
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
    
    def add_to_whitelist(self, username: str) -> bool:
        data = self._load_json(self.whitelist_file)
        username_clean = username.replace("@", "").strip()
        if "users" not in data:
            data["users"] = []
        if username_clean not in data["users"]:
            data["users"].append(username_clean)
            self._save_json(self.whitelist_file, data)
            self.cache.pop('whitelist', None)
            return True
        return False
    
    def remove_from_whitelist(self, username: str) -> bool:
        data = self._load_json(self.whitelist_file)
        username_clean = username.replace("@", "").strip()
        if "users" not in data:
            return False
        if username_clean in data["users"]:
            data["users"].remove(username_clean)
            self._save_json(self.whitelist_file, data)
            self.cache.pop('whitelist', None)
            return True
        return False
    
    def clear_whitelist(self) -> int:
        data = self._load_json(self.whitelist_file)
        removed_count = len(data.get("users", []))
        data["users"] = []
        self._save_json(self.whitelist_file, data)
        self.cache.pop('whitelist', None)
        return removed_count
    
    def get_whitelist_users(self) -> List[str]:
        data = self._load_json(self.whitelist_file)
        return data.get("users", [])
    
    def is_whitelisted(self, username: str) -> bool:
        cache_key = f'whitelist_{username}'
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        data = self._load_json(self.whitelist_file)
        username_clean = username.replace("@", "").strip()
        is_whitelisted = (
            username_clean in data.get("users", []) or 
            str(username_clean) in [str(a) for a in data.get("admins", [])]
        )
        self.cache[cache_key] = is_whitelisted
        return is_whitelisted
    
    def add_event(self, event_data: Dict) -> str:
        data = self._load_json(self.events_file)
        event_id = str(len(data["events"]) + 1)
        event_data["id"] = event_id
        event_data["created_at"] = datetime.now().isoformat()
        data["events"].append(event_data)
        self._save_json(self.events_file, data)
        self.cache.pop('events', None)
        return event_id
    
    def get_events(self) -> List[Dict]:
        if 'events' in self.cache:
            return self.cache['events']
        data = self._load_json(self.events_file)
        self.cache['events'] = data["events"]
        return data["events"]
    
    def delete_event(self, event_id: str) -> bool:
        data = self._load_json(self.events_file)
        initial_len = len(data["events"])
        data["events"] = [e for e in data["events"] if e["id"] != event_id]
        if len(data["events"]) < initial_len:
            self._save_json(self.events_file, data)
            self.cache.pop('events', None)
            return True
        return False
    
    def add_media(self, media_data: Dict) -> None:
        data = self._load_json(self.media_file)
        data["media"].append(media_data)
        self._save_json(self.media_file, data)
        self.cache.pop('media', None)
    
    def search_media(self, query: str = "") -> List[Dict]:
        if 'media' not in self.cache:
            data = self._load_json(self.media_file)
            self.cache['media'] = data["media"]
        if not query:
            return self.cache['media'][-20:]
        query = query.lower()
        return [
            media for media in self.cache['media']
            if query in media.get("name", "").lower() 
            or query in media.get("description", "").lower()
        ]
    
    def _load_json(self, filepath: str) -> Dict:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_json(self, filepath: str, data: Dict) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

db = JSONDatabase()

# ========== ЗАГРУЗКА ЛОГОТИПА ==========
PIL_AVAILABLE = False
LOGO_AVAILABLE = False
logo_image = None
LOGO_SCALE = 0.15
LOGO_POSITION = (20, 20)

try:
    from PIL import Image
    PIL_AVAILABLE = True
    if os.path.exists("logo.png"):
        try:
            logo_image = Image.open("logo.png")
            if logo_image.mode != 'RGBA':
                logo_image = logo_image.convert('RGBA')
            LOGO_AVAILABLE = True
            logger.info(f"✅ Логотип загружен: {logo_image.size}")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки логотипа: {e}")
    else:
        logger.warning("⚠️ Файл logo.png не найден")
except ImportError:
    logger.warning("⚠️ Pillow не установлен")

# ========== GIGACHAT ==========
GIGACHAT_AVAILABLE = False
gigachat_client = None

try:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole
    GIGACHAT_AVAILABLE = True
    try:
        gigachat_client = GigaChat(
            credentials=config.GIGACHAT_SECRET,
            scope=config.GIGACHAT_CLIENT_ID,
            verify_ssl_certs=False
        )
        logger.info("✅ GigaChat клиент инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка GigaChat: {e}")
except ImportError:
    logger.warning("⚠️ GigaChat не установлен")

# ========== AIOGRAM ИНИЦИАЛИЗАЦИЯ ==========
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

bot = Bot(token=config.TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== СОСТОЯНИЯ (FSM) ==========
class PostStates(StatesGroup):
    waiting_for_topic = State()
    waiting_for_clear_confirm = State()

class EventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_date = State()

# ========== MIDDLEWARE ==========
async def check_access_middleware(handler, event: Message, data: dict):
    if not event.from_user:
        return await handler(event, data)
    
    username = event.from_user.username or str(event.from_user.id)
    
    if event.from_user.id in config.ADMIN_IDS:
        return await handler(event, data)
    
    if db.is_whitelisted(username):
        return await handler(event, data)
    
    await event.answer("🔒 У вас нет доступа к боту.\nОбратитесь к администратору.")
    return

dp.message.middleware.register(check_access_middleware)

# ========== КЛАВИАТУРЫ ==========
def get_user_keyboard(is_admin: bool = False):
    keyboard = [
        [types.InlineKeyboardButton(text="🖼️ Обработать фото", callback_data="user_photo")],
        [types.InlineKeyboardButton(text="🤖 Создать пост", callback_data="user_generate_post")],
        [types.InlineKeyboardButton(text="📅 Мероприятия", callback_data="user_events")],
        [types.InlineKeyboardButton(text="📰 СМИ Саратова", callback_data="user_media")],
    ]
    if is_admin:
        keyboard.append([types.InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard():
    keyboard = [
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="👥 Управление пользователями", callback_data="admin_users")],
        [types.InlineKeyboardButton(text="📝 Управление мероприятиями", callback_data="admin_events")],
        [types.InlineKeyboardButton(text="🏢 Управление СМИ", callback_data="admin_media")],
        [types.InlineKeyboardButton(text="🔄 Перезапуск бота", callback_data="admin_restart")],
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="user_menu")],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== ОБРАБОТКА ФОТО ==========
async def process_single_photo_bytes(photo_bytes: bytes) -> BytesIO:
    if not LOGO_AVAILABLE or not PIL_AVAILABLE:
        raise ValueError("Логотип не загружен")
    
    user_image = Image.open(BytesIO(photo_bytes))
    if user_image.mode != 'RGBA':
        user_image = user_image.convert('RGBA')
    
    logo_width = int(user_image.width * LOGO_SCALE)
    logo_height = int(logo_image.height * (logo_width / logo_image.width))
    resized_logo = logo_image.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
    
    position = (user_image.width - logo_width - LOGO_POSITION[0], LOGO_POSITION[1])
    result_image = user_image.copy()
    result_image.paste(resized_logo, position, resized_logo)
    
    output = BytesIO()
    result_image.save(output, format='PNG', quality=95)
    output.seek(0)
    return output

async def process_single_photo_message(message: Message):
    try:
        await message.answer("🔄 Обрабатываю фото...")
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        processed = await process_single_photo_bytes(photo_bytes.read())
        
        await message.answer_photo(
            types.BufferedInputFile(processed.getvalue(), "photo_with_logo.png"),
            caption="✅ Фото обработано с логотипом!"
        )
        
        is_admin = message.from_user.id in config.ADMIN_IDS
        await message.answer("Что дальше?", reply_markup=get_user_keyboard(is_admin))
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await message.answer("❌ Ошибка при обработке фото")

async def process_album_messages(album_messages: List[Message]):
    try:
        photo_count = len(album_messages)
        if photo_count > config.MAX_PHOTOS_PER_BATCH:
            await album_messages[0].answer(f"❌ Слишком много фото. Максимум: {config.MAX_PHOTOS_PER_BATCH}")
            return
        
        status_msg = await album_messages[0].answer(f"🔄 Обрабатываю альбом из {photo_count} фото...")
        processed_photos = []
        
        for i, msg in enumerate(album_messages):
            try:
                photo = msg.photo[-1]
                file = await bot.get_file(photo.file_id)
                photo_bytes = await bot.download_file(file.file_path)
                processed = await process_single_photo_bytes(photo_bytes.read())
                processed_photos.append(processed)
            except Exception as e:
                logger.error(f"Ошибка обработки фото {i+1}: {e}")
                continue
        
        if not processed_photos:
            await status_msg.edit_text("❌ Не удалось обработать ни одного фото")
            return
        
        if len(processed_photos) == 1:
            await album_messages[0].answer_photo(
                types.BufferedInputFile(processed_photos[0].getvalue(), "photo_with_logo.png"),
                caption="✅ Фото обработано!"
            )
        else:
            media_group = []
            for i, processed in enumerate(processed_photos):
                media = InputMediaPhoto(
                    media=types.BufferedInputFile(processed.getvalue(), f"photo_{i+1}_with_logo.png"),
                    caption=f"Альбом {i+1}/{len(processed_photos)}" if i == 0 else ""
                )
                media_group.append(media)
            await album_messages[0].answer_media_group(media_group)
        
        await status_msg.delete()
        is_admin = album_messages[0].from_user.id in config.ADMIN_IDS
        await album_messages[0].answer("Что дальше?", reply_markup=get_user_keyboard(is_admin))
    except Exception as e:
        logger.error(f"Ошибка обработки альбома: {e}")
        await album_messages[0].answer("❌ Ошибка при обработке альбома")

@dp.message(F.photo)
async def handle_photo_message(message: Message):
    if not PIL_AVAILABLE or not LOGO_AVAILABLE:
        await message.answer("❌ Обработка фото временно недоступна")
        return
    
    if message.media_group_id:
        album_storage[message.media_group_id].append(message)
        await asyncio.sleep(1.5)
        
        if message.media_group_id in album_storage:
            album_to_process = album_storage[message.media_group_id].copy()
            del album_storage[message.media_group_id]
            await process_album_messages(album_to_process)
        return
    
    await process_single_photo_message(message)

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer(
        "🤖 **Бот для обработки фото и создания контента**\n\n👇 Выберите действие:",
        reply_markup=get_user_keyboard(is_admin),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "user_menu")
async def user_menu_callback(callback: CallbackQuery):
    is_admin = callback.from_user.id in config.ADMIN_IDS
    await callback.message.edit_text("Главное меню:", reply_markup=get_user_keyboard(is_admin))
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещен")
        return
    await callback.message.edit_text("👑 Админ-панель:", reply_markup=get_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "user_photo")
async def user_photo_callback(callback: CallbackQuery):
    if not LOGO_AVAILABLE:
        await callback.message.answer("❌ Логотип не загружен")
        await callback.answer()
        return
    await callback.message.answer("📸 Отправьте фото боту для обработки")
    await callback.answer()

@dp.callback_query(F.data == "user_generate_post")
async def user_generate_post_callback(callback: CallbackQuery, state: FSMContext):
    if not GIGACHAT_AVAILABLE or not gigachat_client:
        await callback.message.answer("❌ Генерация постов временно недоступна")
        await callback.answer()
        return
    await callback.message.answer("📝 Введите тему для поста:")
    await state.set_state(PostStates.waiting_for_topic)
    await callback.answer()

@dp.message(PostStates.waiting_for_topic)
async def generate_post_process(message: Message, state: FSMContext):
    try:
        await message.answer("🤖 Генерирую пост...")
        prompt = f"Напиши пост на тему: '{message.text}'. На русском, 3-5 предложений, с хэштегами."
        response = gigachat_client.chat(Chat(messages=[Messages(role=MessagesRole.USER, content=prompt)]))
        post_text = response.choices[0].message.content
        await message.answer(f"📋 **Пост:**\n\n{post_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        await message.answer("❌ Ошибка при генерации поста")
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("Выберите действие:", reply_markup=get_user_keyboard(is_admin))

@dp.callback_query(F.data == "user_events")
async def user_events_callback(callback: CallbackQuery):
    events = db.get_events()
    if not events:
        await callback.message.answer("📅 Мероприятий пока нет.")
    else:
        response = "📅 Мероприятия:\n\n"
        for event in events[-5:]:
            response += f"• {event.get('title', 'Без названия')}\n  📅 {event.get('date', 'Дата не указана')}\n\n"
        await callback.message.answer(response)
    await callback.answer()

@dp.callback_query(F.data == "user_media")
async def user_media_callback(callback: CallbackQuery):
    media_list = db.search_media()
    response = "📰 СМИ Саратова:\n\n"
    for media in media_list:
        response += f"• {media.get('name', 'Неизвестно')}\n  {media.get('description', '')[:80]}...\n\n"
    await callback.message.answer(response)
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    stats = f"📊 Статистика:\n• ID бота: {config.BOT_ID}\n• Логотип: {'✅' if LOGO_AVAILABLE else '❌'}"
    await callback.message.answer(stats, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    users = db.get_whitelist_users()
    if not users:
        text = "👥 **Пользователи:**\n\n📭 В списке нет пользователей.\n\n"
    else:
        text = f"👥 **Пользователи:**\n\n📊 Всего: {len(users)}\n\n"
        for i, user in enumerate(users[:20], 1):
            text += f"{i}. @{user}\n"
        if len(users) > 20:
            text += f"... и ещё {len(users) - 20}\n"
        text += "\n"
    
    text += "**Команды:**\n"
    text += "• `/add user @username` — добавить\n"
    text += "• `/remove @username` — удалить\n"
    text += "• `/clear_whitelist` — очистить\n"
    text += "• `/whitelist` — показать список\n"
    
    keyboard = [
        [types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_users")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ]
    await callback.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_"))
async def handle_admin_actions(callback: CallbackQuery):
    action = callback.data
    if action == "admin_events":
        await callback.message.answer("📝 **Мероприятия:**\n• `/add_event`\n• `/events`\n• `/delete_event <id>`", parse_mode="Markdown")
    elif action == "admin_media":
        await callback.message.answer("🏢 **СМИ:**\n• `/add_media`\n• `/media`", parse_mode="Markdown")
    elif action == "admin_restart":
        if not config.BOT_ID:
            await callback.message.answer("❌ BOT_ID не найден")
            await callback.answer()
            return
        keyboard = [[
            types.InlineKeyboardButton(text="✅ Да", callback_data="confirm_restart"),
            types.InlineKeyboardButton(text="❌ Нет", callback_data="cancel_restart")
        ]]
        await callback.message.answer("⚠️ Перезапустить бота?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("add"))
async def add_user_command(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: `/add user @username`", parse_mode="Markdown")
        return
    username = args[2].replace("@", "").strip()
    if db.add_to_whitelist(username):
        await message.answer(f"✅ @{username} добавлен в whitelist")
    else:
        await message.answer(f"ℹ️ @{username} уже в whitelist")

@dp.message(Command("whitelist"))
async def show_whitelist_command(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    users = db.get_whitelist_users()
    if not users:
        await message.answer("📭 В whitelist нет пользователей.")
        return
    response = "👥 **Whitelist:**\n\n"
    for user in users[:50]:
        response += f"• @{user}\n"
    await message.answer(response, parse_mode="Markdown")

@dp.message(Command("remove"))
async def remove_user_command(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: `/remove @username`", parse_mode="Markdown")
        return
    username = args[1].replace("@", "").strip()
    if db.remove_from_whitelist(username):
        await message.answer(f"✅ @{username} удалён из whitelist")
    else:
        await message.answer(f"ℹ️ @{username} не найден в whitelist")

@dp.message(Command("clear_whitelist"))
async def clear_whitelist_command(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.set_state(PostStates.waiting_for_clear_confirm)
    await message.answer("⚠️ **Очистить весь whitelist?**\n\nОтправьте `ДА` для подтверждения или `ОТМЕНА`", parse_mode="Markdown")

@dp.message(PostStates.waiting_for_clear_confirm)
async def confirm_clear_whitelist(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return
    if message.text.strip().upper() in ["ДА", "YES", "Y"]:
        removed = db.clear_whitelist()
        await message.answer(f"✅ Whitelist очищен! Удалено: {removed}")
    else:
        await message.answer("❌ Отменено")
    await state.clear()

@dp.message(Command("add_event"))
async def add_event_start(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer("📝 Введите название:")
    await state.set_state(EventStates.waiting_for_title)

@dp.message(EventStates.waiting_for_title)
async def process_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📄 Введите описание:")
    await state.set_state(EventStates.waiting_for_description)

@dp.message(EventStates.waiting_for_description)
async def process_event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("📅 Введите дату (ДД.ММ.ГГГГ):")
    await state.set_state(EventStates.waiting_for_date)

@dp.message(EventStates.waiting_for_date)
async def process_event_date(message: Message, state: FSMContext):
    data = await state.get_data()
    data["date"] = message.text
    data["creator"] = message.from_user.username or str(message.from_user.id)
    event_id = db.add_event(data)
    await message.answer(f"✅ Мероприятие добавлено! ID: {event_id}")
    await state.clear()

@dp.message(Command("events"))
async def show_events_command(message: Message):
    events = db.get_events()
    if not events:
        await message.answer("📅 Мероприятий пока нет.")
        return
    response = "📅 Мероприятия:\n\n"
    for event in events:
        response += f"• {event.get('title', 'Без названия')}\n  ID: {event.get('id')} | Дата: {event.get('date', 'Не указана')}\n\n"
    await message.answer(response[:4000])

# ========== ПЕРЕЗАПУСК ==========
@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart_callback(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🔄 Перезапускаю...")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{config.get_agent_url()}/api/bots/self/restart",
                headers={'X-Bot-ID': config.BOT_ID},
                timeout=10
            ) as response:
                result = await response.json()
                if result.get('ok'):
                    await callback.message.edit_text("✅ Бот перезапускается...")
                else:
                    await callback.message.edit_text(f"❌ Ошибка: {result.get('msg')}")
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
    await callback.answer()

@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart_callback(callback: CallbackQuery):
    await callback.message.edit_text("❌ Перезапуск отменен.")
    await callback.answer()

# ========== ОЧИСТКА АЛЬБОМОВ ==========
async def cleanup_old_albums():
    while True:
        await asyncio.sleep(300)
        try:
            current_time = datetime.now()
            keys_to_remove = []
            for key in list(album_storage.keys()):
                if album_storage[key]:
                    first_time = datetime.fromtimestamp(album_storage[key][0].date)
                    if (current_time - first_time).total_seconds() > 600:
                        keys_to_remove.append(key)
            for key in keys_to_remove:
                del album_storage[key]
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Запускаю бота...")
    logger.info(f"🤖 Bot ID: {config.BOT_ID}")
    if LOGO_AVAILABLE:
        logger.info(f"✅ Логотип: {logo_image.size}")
    else:
        logger.warning("⚠️ Логотип не загружен")
    
    asyncio.create_task(cleanup_old_albums())
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
