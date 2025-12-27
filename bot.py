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
    GIGACHAT_CLIENT_ID = "019b2405-4854-7d29-9a54-938aa6fff638"
    GIGACHAT_SECRET = "dc515277-136b-41b9-b5e4-dcad944bb94b"
    
    # ID постоянного админа
    ADMIN_IDS = [671065514]
    
    # Настройки обработки фото
    MAX_PHOTOS_PER_BATCH = 10  # Максимум фото за раз
    
    @staticmethod
    def get_agent_url():
        """URL API Bothost"""
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

config = Config()
logger.info(f"✅ Конфигурация загружена")

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

# ========== ЗАГРУЗКА ЛОГОТИПА ==========
PIL_AVAILABLE = False
LOGO_AVAILABLE = False
logo_image = None
LOGO_SCALE = 0.15  # Логотип будет 15% от ширины фото
LOGO_POSITION = (20, 20)  # Правый верхний угол с отступом 20px

try:
    from PIL import Image
    PIL_AVAILABLE = True
    
    # Пробуем загрузить логотип
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
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, Album
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
    
    await event.answer("🔒 У вас нет доступа к боту.\nОбратитесь к администратору.")
    return

dp.message.middleware.register(check_access_middleware)

# ========== ГЛАВНОЕ МЕНЮ ==========
def get_user_keyboard(is_admin: bool = False):
    """Клавиатура для пользователей"""
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

# ========== ФУНКЦИИ ОБРАБОТКИ ФОТО ==========
async def process_single_photo(photo_bytes: bytes) -> BytesIO:
    """Обработать одно фото с логотипом"""
    if not LOGO_AVAILABLE or not PIL_AVAILABLE:
        raise ValueError("Логотип не загружен или Pillow не установлен")
    
    # Открываем фото пользователя
    user_image = Image.open(BytesIO(photo_bytes))
    
    # Конвертируем в RGBA если нужно
    if user_image.mode != 'RGBA':
        user_image = user_image.convert('RGBA')
    
    # Рассчитываем размер логотипа (15% от ширины фото)
    logo_width = int(user_image.width * LOGO_SCALE)
    logo_height = int(logo_image.height * (logo_width / logo_image.width))
    
    # Масштабируем логотип
    resized_logo = logo_image.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
    
    # Позиция логотипа (правый верхний угол)
    position = (
        user_image.width - logo_width - LOGO_POSITION[0],
        LOGO_POSITION[1]
    )
    
    # Создаем копию для наложения
    result_image = user_image.copy()
    
    # Накладываем логотип
    result_image.paste(resized_logo, position, resized_logo)
    
    # Сохраняем результат
    output = BytesIO()
    result_image.save(output, format='PNG', quality=95)
    output.seek(0)
    
    return output

async def process_photo_album(album: Album) -> List[BytesIO]:
    """Обработать альбом фото"""
    processed_photos = []
    photo_count = len(album)
    
    logger.info(f"📸 Начинаю обработку альбома из {photo_count} фото")
    
    if photo_count > config.MAX_PHOTOS_PER_BATCH:
        raise ValueError(f"Слишком много фото. Максимум: {config.MAX_PHOTOS_PER_BATCH}")
    
    for i, message in enumerate(album.messages):
        if not message.photo:
            continue
            
        try:
            # Берем самое качественное фото
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            photo_bytes = await bot.download_file(file.file_path)
            
            # Обрабатываем фото
            processed = await process_single_photo(photo_bytes.read())
            processed_photos.append(processed)
            
            logger.info(f"✅ Обработано фото {i+1}/{photo_count}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки фото {i+1}: {e}")
            continue
    
    return processed_photos

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    """Команда /start"""
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    welcome_text = """
🤖 **Бот для обработки фото и создания контента**

📸 **Обработка фото:**
- Накладывает логотип в правый верхний угол
- Поддерживает до 10 фото за раз (альбомом)
- Сохраняет качество оригинала

✨ **Другие функции:**
- Создание постов через AI
- Управление мероприятиями
- База СМИ Саратова

👇 **Выберите действие:**
"""
    
    await message.answer(
        welcome_text,
        reply_markup=get_user_keyboard(is_admin),
        parse_mode="Markdown"
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
    if not LOGO_AVAILABLE:
        await callback.message.answer(
            "❌ Логотип не загружен.\n"
            "Убедитесь, что файл logo.png находится в папке с ботом."
        )
        await callback.answer()
        return
    
    instructions = """
📸 **Как обработать фото:**

**Для одного фото:**
1. Просто отправьте фото боту

**Для нескольких фото (до 10):**
1. Откройте галерею
2. Выберите нужные фото (удерживайте для выбора)
3. Нажмите "Отправить как альбом"
4. Бот обработает все фото сразу

⚡ **Что делает бот:**
- Накладывает логотип в правый верхний угол
- Автоматически подбирает размер логотипа
- Сохраняет оригинальное качество
- Поддерживает PNG и JPEG

👇 **Просто отправьте фото(а) сейчас:**
"""
    
    await callback.message.answer(instructions, parse_mode="Markdown")
    await callback.answer()

# ========== ОБРАБОТКА ОДНОГО ФОТО ==========
@dp.message(F.photo)
async def handle_single_photo(message: Message):
    """Обработка одного фото (не альбом)"""
    if not PIL_AVAILABLE:
        await message.answer("❌ Обработка фото временно недоступна")
        return
    
    if not LOGO_AVAILABLE:
        await message.answer(
            "❌ Логотип не загружен.\n"
            "Убедитесь, что файл logo.png находится в папке с ботом."
        )
        return
    
    # Проверяем, является ли это частью альбома
    if message.media_group_id:
        # Это часть альбома - обработается в handle_album
        return
    
    try:
        await message.answer("🔄 Обрабатываю фото...")
        
        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        
        # Обрабатываем
        processed = await process_single_photo(photo_bytes.read())
        
        # Отправляем результат
        await message.answer_photo(
            types.BufferedInputFile(processed.getvalue(), "photo_with_logo.png"),
            caption="✅ Фото обработано с логотипом!"
        )
        
        # Показываем меню
        is_admin = message.from_user.id in config.ADMIN_IDS
        await message.answer(
            "Что дальше?",
            reply_markup=get_user_keyboard(is_admin)
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки одного фото: {e}")
        await message.answer("❌ Ошибка при обработке фото")

# ========== ОБРАБОТКА АЛЬБОМА (МЕДИА-ГРУППЫ) ==========
@dp.message(F.media_group_id, F.content_type.in_({'photo'}))
async def handle_album(message: Message, album: Album = None):
    """Обработка альбома фото"""
    if not PIL_AVAILABLE or not LOGO_AVAILABLE:
        await message.answer("❌ Обработка фото временно недоступна")
        return
    
    try:
        # Проверяем количество фото
        photo_count = len(album)
        
        if photo_count > config.MAX_PHOTOS_PER_BATCH:
            await message.answer(
                f"❌ Слишком много фото.\n"
                f"Вы отправили: {photo_count}\n"
                f"Максимум: {config.MAX_PHOTOS_PER_BATCH}\n\n"
                f"Пожалуйста, отправьте меньше фото."
            )
            return
        
        # Отправляем уведомление о начале обработки
        status_msg = await message.answer(f"🔄 Обрабатываю альбом из {photo_count} фото...")
        
        # Обрабатываем все фото в альбоме
        processed_photos = await process_photo_album(album)
        
        if not processed_photos:
            await status_msg.edit_text("❌ Не удалось обработать ни одного фото")
            return
        
        # Отправляем результаты
        if len(processed_photos) == 1:
            # Одно фото
            await message.answer_photo(
                types.BufferedInputFile(
                    processed_photos[0].getvalue(), 
                    "photo_with_logo.png"
                ),
                caption="✅ Фото обработано с логотипом!"
            )
        else:
            # Несколько фото - отправляем как альбом
            media_group = []
            for i, processed in enumerate(processed_photos):
                media = InputMediaPhoto(
                    media=types.BufferedInputFile(
                        processed.getvalue(),
                        f"photo_{i+1}_with_logo.png"
                    ),
                    caption=f"Фото {i+1} с логотипом" if i == 0 else ""
                )
                media_group.append(media)
            
            # Отправляем альбом
            await message.answer_media_group(media_group)
            
            # Отправляем отдельное сообщение с итогом
            await message.answer(f"✅ Обработано {len(processed_photos)} фото с логотипом!")
        
        # Удаляем статусное сообщение
        await status_msg.delete()
        
        # Показываем меню
        is_admin = message.from_user.id in config.ADMIN_IDS
        await message.answer(
            "Что дальше?",
            reply_markup=get_user_keyboard(is_admin)
        )
        
    except ValueError as e:
        logger.error(f"Ошибка валидации: {e}")
        await message.answer(f"❌ {str(e)}")
    except Exception as e:
        logger.error(f"Ошибка обработки альбома: {e}")
        await message.answer("❌ Ошибка при обработке фото")

# ========== ГЕНЕРАЦИЯ ПОСТОВ ==========
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

@dp.message(PostStates.waiting_for_topic)
async def generate_post_process(message: Message, state: FSMContext):
    """Сгенерировать пост"""
    try:
        await message.answer("🤖 Генерирую пост...")
        
        prompt = f"Напиши качественный пост для соцсетей на тему: '{message.text}'. На русском языке, 3-5 предложений, с хэштегами."
        
        response = gigachat_client.chat(
            Chat(messages=[Messages(role=MessagesRole.USER, content=prompt)])
        )
        
        post_text = response.choices[0].message.content
        
        await message.answer(f"📋 **Сгенерированный пост:**\n\n{post_text}", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка генерации поста: {e}")
        await message.answer("❌ Ошибка при генерации поста")
    
    await state.clear()
    
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer(
        "Выберите следующее действие:",
        reply_markup=get_user_keyboard(is_admin)
    )

# ========== МЕРОПРИЯТИЯ И СМИ ==========
@dp.callback_query(F.data == "user_events")
async def user_events_callback(callback: CallbackQuery):
    """Показать мероприятия"""
    events = db.get_events()
    
    if not events:
        await callback.message.answer("📅 Мероприятий пока нет.")
    else:
        response = "📅 Ближайшие мероприятия:\n\n"
        for event in events[-5:]:
            response += f"• {event.get('title', 'Без названия')}\n"
            response += f"  📅 {event.get('date', 'Дата не указана')}\n\n"
        
        await callback.message.answer(response)
    
    await callback.answer()

@dp.callback_query(F.data == "user_media")
async def user_media_callback(callback: CallbackQuery):
    """Показать СМИ"""
    media_list = db.search_media()
    
    response = "📰 СМИ Саратова:\n\n"
    for media in media_list:
        response += f"• {media.get('name', 'Неизвестно')}\n"
        response += f"  {media.get('description', '')[:80]}...\n\n"
    
    await callback.message.answer(response)
    await callback.answer()

# ========== АДМИН-ДЕЙСТВИЯ ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    stats_text = f"📊 **Статистика:**\n\n• ID бота: {config.BOT_ID}\n• Логотип: {'✅' if LOGO_AVAILABLE else '❌'}\n• Максимум фото: {config.MAX_PHOTOS_PER_BATCH}"
    await callback.message.answer(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_"))
async def handle_admin_actions(callback: CallbackQuery):
    """Обработка остальных админ-действий"""
    action = callback.data
    
    if action == "admin_users":
        text = "👥 **Управление пользователями:**\n\nИспользуйте команды:\n• `/add user @username`\n• `/list_users`"
        await callback.message.answer(text, parse_mode="Markdown")
    
    elif action == "admin_events":
        text = "📝 **Управление мероприятиями:**\n\nКоманды:\n• `/add_event`\n• `/events`\n• `/delete_event <id>`"
        await callback.message.answer(text, parse_mode="Markdown")
    
    elif action == "admin_media":
        text = "🏢 **Управление СМИ:**\n\nКоманды:\n• `/add_media \"Название\" \"Описание\"`\n• `/media`"
        await callback.message.answer(text, parse_mode="Markdown")
    
    elif action == "admin_restart":
        if not config.BOT_ID:
            await callback.message.answer("❌ BOT_ID не найден")
            await callback.answer()
            return
        
        keyboard = [[
            types.InlineKeyboardButton(text="✅ Да", callback_data="confirm_restart"),
            types.InlineKeyboardButton(text="❌ Нет", callback_data="cancel_restart")
        ]]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.answer("⚠️ Перезапустить бота?", reply_markup=markup)
    
    await callback.answer()

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("add"))
async def add_user_command(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /add user @username")
        return
    
    username = args[2].replace("@", "")
    if db.add_to_whitelist(username):
        await message.answer(f"✅ @{username} добавлен в whitelist")
    else:
        await message.answer(f"ℹ️ @{username} уже в whitelist")

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
    
    response = "📅 Все мероприятия:\n\n"
    for event in events:
        response += f"• {event.get('title', 'Без названия')}\n"
        response += f"  ID: {event.get('id')} | Дата: {event.get('date', 'Не указана')}\n\n"
    
    await message.answer(response[:4000])

# ========== ПЕРЕЗАПУСК БОТА ==========
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

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("🚀 Запускаю Telegram бота...")
    logger.info(f"🤖 Bot ID: {config.BOT_ID}")
    
    if LOGO_AVAILABLE:
        logger.info(f"✅ Логотип загружен: {logo_image.size}")
        logger.info(f"⚙️  Масштаб логотипа: {LOGO_SCALE*100}% от ширины фото")
    else:
        logger.warning("⚠️ Логотип не загружен - обработка фото недоступна")
    
    logger.info(f"📸 Максимум фото за раз: {config.MAX_PHOTOS_PER_BATCH}")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
