import os
import sys
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Any
from io import BytesIO

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
    # Получаем токен из переменных окружения Bothost
    TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TOKEN')
    if not TOKEN:
        logger.error("❌ Не найден BOT_TOKEN в переменных окружения!")
        raise ValueError("Установите BOT_TOKEN в настройках Bothost")
    
    # Переменные Bothost
    BOT_ID = os.getenv('BOT_ID', '')
    USER_ID = os.getenv('USER_ID', '')
    
    # GigaChat API (ваши данные)
    GIGACHAT_CLIENT_ID = "019b2405-4854-7d29-9a54-938aa6fff638"  # Ваш Client ID
    GIGACHAT_SECRET = "dc515277-136b-41b9-b5e4-dcad944bb94b"     # Ваш Secret
    
    # ID постоянного админа
    ADMIN_IDS = [671065514]  # Ваш ID
    
    @staticmethod
    def get_agent_url():
        """URL API Bothost"""
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

config = Config()
logger.info(f"✅ Конфигурация загружена")
logger.info(f"👑 Админ ID: {config.ADMIN_IDS}")

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
        """Инициализация JSON файлов"""
        defaults = {
            self.whitelist_file: {"users": [], "admins": config.ADMIN_IDS},
            self.events_file: {"events": []},
            self.media_file: {"media": [
                {
                    "name": "Саратовские вести",
                    "description": "Городская газета",
                    "added_by": "system",
                    "added_at": datetime.now().isoformat()
                },
                {
                    "name": "Саратов 24",
                    "description": "Новостной портал",
                    "added_by": "system",
                    "added_at": datetime.now().isoformat()
                },
                {
                    "name": "Комсомольская правда - Саратов",
                    "description": "Региональное издание",
                    "added_by": "system",
                    "added_at": datetime.now().isoformat()
                }
            ]}
        }
        
        for file, default_data in defaults.items():
            if not os.path.exists(file):
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
                logger.info(f"Создан файл: {file}")
    
    def add_to_whitelist(self, username: str) -> bool:
        data = self._load_json(self.whitelist_file)
        if username not in data["users"]:
            data["users"].append(username)
            self._save_json(self.whitelist_file, data)
            self.cache.pop('whitelist', None)
            return True
        return False
    
    def is_whitelisted(self, username: str) -> bool:
        cache_key = f'whitelist_{username}'
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        data = self._load_json(self.whitelist_file)
        is_whitelisted = username in data["users"] or username in data["admins"]
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
logger.info("✅ База данных инициализирована")

# ========== ПРОВЕРКА ЗАВИСИМОСТЕЙ ==========
PIL_AVAILABLE = False
LOGO_AVAILABLE = False
logo_image = None

try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
    PIL_AVAILABLE = True
    logger.info("✅ Pillow доступен для обработки изображений")
    
    # Пробуем загрузить логотип
    try:
        if os.path.exists("logo.png"):
            logo_image = Image.open("logo.png")
            LOGO_AVAILABLE = True
            logger.info("✅ Логотип logo.png загружен")
        else:
            logger.warning("⚠️ Файл logo.png не найден в папке с ботом")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки логотипа: {e}")
        
except ImportError as e:
    logger.warning(f"⚠️ Pillow не установлен: {e}")

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
        
except ImportError as e:
    logger.warning(f"⚠️ GigaChat не установлен: {e}")

# ========== AIOGRAM ИНИЦИАЛИЗАЦИЯ ==========
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

bot = Bot(token=config.TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== СОСТОЯНИЯ (FSM) ==========
class PostStates(StatesGroup):
    waiting_for_topic = State()

class EventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_date = State()

# ========== MIDDLEWARE ==========
async def check_access_middleware(handler, event: Message, data: dict):
    """Проверка доступа пользователя"""
    if not event.from_user:
        return await handler(event, data)
    
    username = event.from_user.username or str(event.from_user.id)
    
    # Админы всегда имеют доступ
    if event.from_user.id in config.ADMIN_IDS:
        return await handler(event, data)
    
    # Проверка whitelist
    if db.is_whitelisted(username):
        return await handler(event, data)
    
    # Для новых пользователей показываем сообщение о доступе
    await event.answer(
        "🔒 У вас нет доступа к боту.\n\n"
        "Пожалуйста, обратитесь к администратору для получения доступа."
    )
    return

dp.message.middleware.register(check_access_middleware)

# ========== ГЛАВНОЕ МЕНЮ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========
def get_user_keyboard(is_admin: bool = False):
    """Клавиатура для пользователей"""
    keyboard = [
        [types.InlineKeyboardButton(text="🖼️ Обработать фото", callback_data="user_photo")],
        [types.InlineKeyboardButton(text="🤖 Создать пост", callback_data="user_generate_post")],
        [types.InlineKeyboardButton(text="📅 Мероприятия", callback_data="user_events")],
        [types.InlineKeyboardButton(text="📰 СМИ Саратова", callback_data="user_media")],
        [types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="user_help")],
    ]
    
    # Добавляем админ-панель только для админов
    if is_admin:
        keyboard.append([types.InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== АДМИН-ПАНЕЛЬ ==========
def get_admin_keyboard():
    """Клавиатура для администраторов"""
    keyboard = [
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="👥 Управление пользователями", callback_data="admin_users")],
        [types.InlineKeyboardButton(text="📝 Управление мероприятиями", callback_data="admin_events")],
        [types.InlineKeyboardButton(text="🏢 Управление СМИ", callback_data="admin_media")],
        [types.InlineKeyboardButton(text="🔄 Перезапуск бота", callback_data="admin_restart")],
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="user_menu")],
    ]
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    """Команда /start"""
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    welcome_text = """
🤖 Добро пожаловать в бот!

Выберите действие из меню ниже:
"""
    
    await message.answer(
        welcome_text,
        reply_markup=get_user_keyboard(is_admin)
    )

@dp.callback_query(F.data == "user_menu")
async def user_menu_callback(callback: CallbackQuery):
    """Вернуться в главное меню"""
    is_admin = callback.from_user.id in config.ADMIN_IDS
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=get_user_keyboard(is_admin)
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    """Показать админ-панель"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "👑 Админ-панель:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

# ========== ПОЛЬЗОВАТЕЛЬСКИЕ ДЕЙСТВИЯ ==========
@dp.callback_query(F.data == "user_photo")
async def user_photo_callback(callback: CallbackQuery):
    """Обработка фото"""
    await callback.message.answer(
        "📸 Отправьте фото для обработки.\n\n"
        "Бот добавит логотип и применит фильтры."
    )
    await callback.answer()

@dp.callback_query(F.data == "user_generate_post")
async def user_generate_post_callback(callback: CallbackQuery, state: FSMContext):
    """Создание поста"""
    if not GIGACHAT_AVAILABLE or not gigachat_client:
        await callback.message.answer("❌ Генерация постов временно недоступна")
        await callback.answer()
        return
    
    await callback.message.answer("📝 Введите тему для поста:")
    await state.set_state(PostStates.waiting_for_topic)
    await callback.answer()

@dp.callback_query(F.data == "user_events")
async def user_events_callback(callback: CallbackQuery):
    """Показать мероприятия"""
    events = db.get_events()
    
    if not events:
        await callback.message.answer("📅 Мероприятий пока нет.")
        await callback.answer()
        return
    
    response = "📅 Ближайшие мероприятия:\n\n"
    for event in events[-5:]:
        response += f"• {event.get('title', 'Без названия')}\n"
        response += f"  📅 {event.get('date', 'Дата не указана')}\n"
        if event.get('description'):
            response += f"  📝 {event.get('description')[:60]}...\n"
        response += "\n"
    
    await callback.message.answer(response)
    await callback.answer()

@dp.callback_query(F.data == "user_media")
async def user_media_callback(callback: CallbackQuery):
    """Показать СМИ"""
    media_list = db.search_media()
    
    if not media_list:
        await callback.message.answer("📰 База СМИ Саратова пуста.")
        await callback.answer()
        return
    
    response = "📰 СМИ Саратова:\n\n"
    for media in media_list:
        response += f"• {media.get('name', 'Неизвестно')}\n"
        if media.get('description'):
            response += f"  {media.get('description')[:80]}...\n"
        response += "\n"
    
    await callback.message.answer(response)
    await callback.answer()

@dp.callback_query(F.data == "user_help")
async def user_help_callback(callback: CallbackQuery):
    """Помощь"""
    help_text = """
ℹ️ **Помощь по боту:**

**Основные функции:**
1. 🖼️ **Обработка фото** - отправьте фото, бот добавит логотип
2. 🤖 **Создание поста** - генерация текста через AI
3. 📅 **Мероприятия** - просмотр событий
4. 📰 **СМИ Саратова** - база местных СМИ

**Как использовать:**
- Выберите действие из меню
- Следуйте инструкциям бота
- Для обработки фото просто отправьте изображение

**Контакты:**
По вопросам доступа обращайтесь к администратору.
"""
    
    await callback.message.answer(help_text, parse_mode="Markdown")
    await callback.answer()

# ========== ОБРАБОТКА ФОТО С ЛОГОТИПОМ ==========
@dp.message(F.photo)
async def process_photo_with_logo(message: Message):
    """Обработка фото с наложением логотипа"""
    if not PIL_AVAILABLE:
        await message.answer("❌ Обработка фото временно недоступна")
        return
    
    if not LOGO_AVAILABLE:
        await message.answer("❌ Логотип не найден. Убедитесь, что файл logo.png находится в папке с ботом.")
        return
    
    try:
        await message.answer("🔄 Обрабатываю фото...")
        
        # Скачиваем фото пользователя
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        
        # Открываем фото пользователя
        user_image = Image.open(BytesIO(photo_bytes.read()))
        
        # Изменяем размер логотипа (максимум 20% от ширины фото)
        logo_width = user_image.width // 5
        logo_height = int(logo_image.height * (logo_width / logo_image.width))
        resized_logo = logo_image.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        
        # Создаем прозрачный слой для логотипа
        logo_with_alpha = resized_logo.copy()
        if logo_with_alpha.mode != 'RGBA':
            logo_with_alpha = logo_with_alpha.convert('RGBA')
        
        # Позиция логотипа (правый нижний угол с отступом)
        position = (
            user_image.width - logo_width - 20,
            user_image.height - logo_height - 20
        )
        
        # Накладываем логотип
        user_image.paste(logo_with_alpha, position, logo_with_alpha)
        
        # Применяем фильтр для улучшения качества
        user_image = user_image.filter(ImageFilter.SHARPEN)
        
        # Сохраняем результат
        output = BytesIO()
        user_image.save(output, format='JPEG', quality=95)
        output.seek(0)
        
        # Отправляем обработанное фото
        await message.answer_photo(
            types.BufferedInputFile(output.getvalue(), "photo_with_logo.jpg"),
            caption="✅ Фото обработано с логотипом!"
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await message.answer("❌ Ошибка при обработке фото")

# ========== ГЕНЕРАЦИЯ ПОСТОВ ЧЕРЕЗ GIGACHAT ==========
@dp.message(PostStates.waiting_for_topic)
async def generate_post_process(message: Message, state: FSMContext):
    """Сгенерировать пост"""
    try:
        await message.answer("🤖 Генерирую пост...")
        
        # Создаем промпт
        prompt = (
            f"Напиши качественный пост для соцсетей на тему: '{message.text}'. "
            "Требования:\n"
            "1. На русском языке\n"
            "2. 3-5 предложений\n"
            "3. Интересный и вовлекающий\n"
            "4. Добавь 2-3 хэштега в конце\n"
            "5. Стиль: дружеский, но профессиональный"
        )
        
        # Генерируем через GigaChat
        response = gigachat_client.chat(
            Chat(messages=[Messages(role=MessagesRole.USER, content=prompt)])
        )
        
        post_text = response.choices[0].message.content
        
        # Отправляем результат
        await message.answer(f"📋 **Сгенерированный пост:**\n\n{post_text}", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка генерации поста: {e}")
        await message.answer("❌ Ошибка при генерации поста. Попробуйте позже.")
    
    await state.clear()
    
    # Показываем меню
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer(
        "Выберите следующее действие:",
        reply_markup=get_user_keyboard(is_admin)
    )

# ========== АДМИН-ДЕЙСТВИЯ ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    """Статистика"""
    events_count = len(db.get_events())
    media_count = len(db.search_media())
    
    stats_text = (
        f"📊 **Статистика бота:**\n\n"
        f"• Мероприятий в базе: {events_count}\n"
        f"• СМИ в базе: {media_count}\n"
        f"• ID бота: {config.BOT_ID}\n"
        f"• Бот запущен и работает"
    )
    
    await callback.message.answer(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    """Управление пользователями"""
    users_text = (
        "👥 **Управление пользователями:**\n\n"
        "**Команды для админов:**\n"
        "• `/add user @username` - добавить пользователя в whitelist\n"
        "• `/list_users` - показать всех пользователей\n\n"
        "**Постоянный админ:**\n"
        f"• ID: {config.ADMIN_IDS[0]}"
    )
    
    await callback.message.answer(users_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_events")
async def admin_events_callback(callback: CallbackQuery):
    """Управление мероприятиями"""
    events_text = (
        "📝 **Управление мероприятиями:**\n\n"
        "**Команды:**\n"
        "• `/add_event` - добавить мероприятие\n"
        "• `/events` - список мероприятий\n"
        "• `/delete_event <id>` - удалить мероприятие\n\n"
        "**Инструкция:**\n"
        "1. Используйте /add_event для добавления\n"
        "2. Следуйте инструкциям бота\n"
        "3. Для удаления используйте ID мероприятия"
    )
    
    await callback.message.answer(events_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_media")
async def admin_media_callback(callback: CallbackQuery):
    """Управление СМИ"""
    media_text = (
        "🏢 **Управление СМИ Саратова:**\n\n"
        "**Команды:**\n"
        "• `/add_media \"Название\" \"Описание\"` - добавить СМИ\n"
        "• `/media` - просмотр базы СМИ\n\n"
        "**Пример:**\n"
        "`/add_media \"Саратов Сегодня\" \"Главный новостной портал города\"`\n\n"
        "**Уже в базе:**\n"
        "• Саратовские вести\n"
        "• Саратов 24\n"
        "• Комсомольская правда - Саратов"
    )
    
    await callback.message.answer(media_text, parse_mode="Markdown")
    await callback.answer()

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("add"))
async def add_user_command(message: Message):
    """Добавить пользователя в whitelist"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /add user @username")
        return
    
    username = args[2].replace("@", "")
    if db.add_to_whitelist(username):
        await message.answer(f"✅ Пользователь @{username} добавлен в whitelist!")
    else:
        await message.answer(f"ℹ️ Пользователь @{username} уже в whitelist")

@dp.message(Command("list_users"))
async def list_users_command(message: Message):
    """Показать всех пользователей"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    # Здесь можно добавить логику для отображения пользователей
    await message.answer("👥 Функция отображения пользователей в разработке")

@dp.message(Command("add_event"))
async def add_event_start(message: Message, state: FSMContext):
    """Начать добавление мероприятия"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
        return
    
    await message.answer("📝 Введите название мероприятия:")
    await state.set_state(EventStates.waiting_for_title)

@dp.message(EventStates.waiting_for_title)
async def process_event_title(message: Message, state: FSMContext):
    """Обработать название мероприятия"""
    await state.update_data(title=message.text)
    await message.answer("📄 Введите описание мероприятия:")
    await state.set_state(EventStates.waiting_for_description)

@dp.message(EventStates.waiting_for_description)
async def process_event_description(message: Message, state: FSMContext):
    """Обработать описание мероприятия"""
    await state.update_data(description=message.text)
    await message.answer("📅 Введите дату мероприятия (например: 25.12.2024):")
    await state.set_state(EventStates.waiting_for_date)

@dp.message(EventStates.waiting_for_date)
async def process_event_date(message: Message, state: FSMContext):
    """Обработать дату и сохранить мероприятие"""
    data = await state.get_data()
    data["date"] = message.text
    data["creator"] = message.from_user.username or str(message.from_user.id)
    
    event_id = db.add_event(data)
    await message.answer(f"✅ Мероприятие добавлено! ID: {event_id}")
    await state.clear()

@dp.message(Command("events"))
async def show_events_command(message: Message):
    """Показать мероприятия"""
    events = db.get_events()
    
    if not events:
        await message.answer("📅 Мероприятий пока нет.")
        return
    
    response = "📅 Все мероприятия:\n\n"
    for event in events:
        response += f"• **{event.get('title', 'Без названия')}**\n"
        response += f"  ID: {event.get('id')}\n"
        response += f"  Дата: {event.get('date', 'Не указана')}\n"
        if event.get('description'):
            response += f"  Описание: {event.get('description')[:100]}...\n"
        response += f"  Создатель: {event.get('creator', 'Неизвестно')}\n\n"
    
    await message.answer(response[:4000], parse_mode="Markdown")

@dp.message(Command("delete_event"))
async def delete_event_command(message: Message):
    """Удалить мероприятие"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /delete_event <id_мероприятия>")
        return
    
    event_id = args[1]
    if db.delete_event(event_id):
        await message.answer(f"✅ Мероприятие {event_id} удалено!")
    else:
        await message.answer(f"❌ Мероприятие с ID {event_id} не найдено.")

@dp.message(Command("add_media"))
async def add_media_command(message: Message):
    """Добавить СМИ в базу"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer('Использование: /add_media "Название СМИ" "Описание"')
        return
    
    media_data = {
        "name": args[1],
        "description": args[2],
        "added_by": message.from_user.username or str(message.from_user.id),
        "added_at": datetime.now().isoformat()
    }
    
    db.add_media(media_data)
    await message.answer(f"✅ СМИ '{args[1]}' добавлено в базу!")

@dp.message(Command("media"))
async def show_media_command(message: Message):
    """Показать базу СМИ"""
    media_list = db.search_media()
    
    if not media_list:
        await message.answer("📰 База СМИ Саратова пуста.")
        return
    
    response = "📰 База СМИ Саратова:\n\n"
    for media in media_list:
        response += f"• **{media.get('name', 'Неизвестно')}**\n"
        if media.get('description'):
            response += f"  {media.get('description')}\n"
        response += f"  Добавлено: {media.get('added_by', 'системой')}\n\n"
    
    await message.answer(response[:4000], parse_mode="Markdown")

# ========== ПЕРЕЗАПУСК БОТА (BOTHOST API) ==========
@dp.callback_query(F.data == "admin_restart")
async def admin_restart_callback(callback: CallbackQuery):
    """Перезапуск бота"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    if not config.BOT_ID:
        await callback.message.answer("❌ BOT_ID не найден")
        await callback.answer()
        return
    
    # Кнопки подтверждения
    keyboard = [[
        types.InlineKeyboardButton(text="✅ Да, перезапустить", callback_data="confirm_restart"),
        types.InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_restart")
    ]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.answer(
        "⚠️ **Внимание!**\n\n"
        "Вы уверены, что хотите перезапустить бота?\n"
        "Бот будет перезагружен через API Bothost.",
        reply_markup=markup
    )
    await callback.answer()

@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart_callback(callback: CallbackQuery):
    """Подтверждение перезапуска"""
    try:
        await callback.message.edit_text("🔄 Отправляю запрос на перезапуск...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{config.get_agent_url()}/api/bots/self/restart",
                headers={'X-Bot-ID': config.BOT_ID},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()
                
                if result.get('ok'):
                    await callback.message.edit_text(f"✅ {result.get('message', 'Бот перезапускается...')}")
                else:
                    await callback.message.edit_text(f"❌ Ошибка: {result.get('msg', 'Неизвестная ошибка')}")
                    
    except Exception as e:
        logger.error(f"Ошибка перезапуска: {e}")
        await callback.message.edit_text(f"❌ Ошибка подключения: {str(e)}")
    
    await callback.answer()

@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart_callback(callback: CallbackQuery):
    """Отмена перезапуска"""
    await callback.message.edit_text("❌ Перезапуск отменен.")
    await callback.answer()

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска"""
    logger.info("🚀 Запускаю Telegram бота...")
    logger.info(f"🤖 Bot ID: {config.BOT_ID}")
    logger.info(f"👑 Админ ID: {config.ADMIN_IDS}")
    
    if LOGO_AVAILABLE:
        logger.info("✅ Логотип готов к использованию")
    else:
        logger.warning("⚠️ Логотип не загружен")
    
    if GIGACHAT_AVAILABLE and gigachat_client:
        logger.info("✅ GigaChat готов к работе")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
