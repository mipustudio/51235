import os
import sys
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
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
        available_vars = [k for k in os.environ.keys() if 'TOKEN' in k or 'BOT' in k]
        logger.error(f"Доступные переменные с токенами: {available_vars}")
        raise ValueError("Установите BOT_TOKEN в настройках Bothost")
    
    # Переменные Bothost
    BOT_ID = os.getenv('BOT_ID', '')
    USER_ID = os.getenv('USER_ID', '')
    DOMAIN = os.getenv('DOMAIN', '')
    PORT = int(os.getenv('PORT', '3000'))
    
    # GigaChat API
    GIGACHAT_CLIENT_ID = os.getenv('019b2405-4854-7d29-9a54-938aa6fff638', '')
    GIGACHAT_SECRET = os.getenv('dc515277-136b-41b9-b5e4-dcad944bb94b', '')
    
    # Получаем ID админов
    admin_ids_str = os.getenv('671065514', '')
    ADMIN_IDS = []
    if admin_ids_str:
        for id_str in admin_ids_str.split(","):
            try:
                ADMIN_IDS.append(int(id_str.strip()))
            except ValueError:
                logger.warning(f"Некорректный ID админа: {id_str}")
    
    # Если нет админов, используем USER_ID как админа
    if not ADMIN_IDS and USER_ID:
        try:
            ADMIN_IDS.append(int(USER_ID))
            logger.info(f"USER_ID добавлен как администратор: {USER_ID}")
        except ValueError:
            pass
    
    @staticmethod
    def get_agent_url():
        """URL API Bothost"""
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

config = Config()
logger.info(f"✅ Конфигурация загружена: BOT_ID={config.BOT_ID}, USER_ID={config.USER_ID}")

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
            self.whitelist_file: {"users": [], "admins": []},
            self.events_file: {"events": []},
            self.media_file: {"media": []}
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
            return self.cache['media'][-20:]  # Последние 20
        
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
try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
    PIL_AVAILABLE = True
    logger.info("✅ Pillow доступен для обработки изображений")
except ImportError as e:
    logger.warning(f"⚠️ Pillow не установлен: {e}")

GIGACHAT_AVAILABLE = False
gigachat_client = None
try:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole
    GIGACHAT_AVAILABLE = True
    
    if config.GIGACHAT_CLIENT_ID and config.GIGACHAT_SECRET:
        try:
            gigachat_client = GigaChat(
                credentials=config.GIGACHAT_SECRET,
                scope=config.GIGACHAT_CLIENT_ID,
                verify_ssl_certs=False
            )
            logger.info("✅ GigaChat клиент инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка GigaChat: {e}")
    else:
        logger.warning("⚠️ GigaChat не настроен")
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
        logger.debug(f"Доступ для админа {username}")
        return await handler(event, data)
    
    # Проверка whitelist
    if db.is_whitelisted(username):
        logger.debug(f"Доступ для пользователя {username}")
        return await handler(event, data)
    
    logger.warning(f"Доступ запрещен для {username}")
    await event.answer("⛔ У вас нет доступа к боту. Обратитесь к администратору.")
    return

dp.message.middleware.register(check_access_middleware)

# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    """Команда /start"""
    welcome = """
🤖 Добро пожаловать в бот!

Основные команды:
/admin - админ-панель
/add user @username - добавить пользователя
/generate_post - создать пост через AI
/events - список мероприятий
/add_event - добавить мероприятие
/media - база СМИ Саратова
/help - помощь

Отправьте фото для обработки с логотипом!
"""
    await message.answer(welcome)

@dp.message(Command("help"))
async def help_command(message: Message):
    """Команда /help"""
    await start_command(message)

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ-панель"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
        return
    
    keyboard = [
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📝 Мероприятия", callback_data="admin_events")],
        [types.InlineKeyboardButton(text="🏢 СМИ", callback_data="admin_media")],
        [types.InlineKeyboardButton(text="🔄 Перезапуск", callback_data="admin_restart")],
    ]
    
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("👑 Админ-панель:", reply_markup=markup)

@dp.message(Command("add"))
async def add_to_whitelist(message: Message):
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
        await message.answer(f"✅ @{username} добавлен в whitelist")
    else:
        await message.answer(f"ℹ️ @{username} уже в whitelist")

# ========== ОБРАБОТКА ФОТО ==========
@dp.message(F.photo)
async def process_photo(message: Message):
    """Обработка фото с логотипом"""
    if not PIL_AVAILABLE:
        await message.answer("❌ Обработка фото недоступна (Pillow не установлен)")
        return
    
    try:
        await message.answer("🔄 Обрабатываю фото...")
        
        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        
        # Открываем и обрабатываем
        image = Image.open(BytesIO(photo_bytes.read()))
        
        # Применяем фильтр
        image = image.filter(ImageFilter.SHARPEN)
        
        # Добавляем текст (логотип)
        draw = ImageDraw.Draw(image)
        try:
            # Пробуем загрузить шрифт
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()
        
        # Добавляем текст в угол
        text = "SARATOV"
        draw.text((20, 20), text, font=font, fill=(255, 255, 255, 200))
        
        # Сохраняем
        output = BytesIO()
        image.save(output, format='JPEG', quality=90)
        output.seek(0)
        
        # Отправляем результат
        await message.answer_photo(
            types.BufferedInputFile(output.getvalue(), "processed.jpg"),
            caption="✅ Фото обработано с логотипом!"
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await message.answer("❌ Ошибка при обработке фото")

# ========== ГЕНЕРАЦИЯ ПОСТОВ ==========
@dp.message(Command("generate_post"))
async def generate_post_start(message: Message, state: FSMContext):
    """Начать генерацию поста"""
    if not GIGACHAT_AVAILABLE or not gigachat_client:
        await message.answer("❌ Генерация постов недоступна (GigaChat не настроен)")
        return
    
    await message.answer("📝 Введите тему для поста:")
    await state.set_state(PostStates.waiting_for_topic)

@dp.message(PostStates.waiting_for_topic)
async def generate_post_process(message: Message, state: FSMContext):
    """Сгенерировать пост"""
    try:
        await message.answer("🤖 Генерирую пост...")
        
        prompt = f"Напиши интересный пост на тему: {message.text}. Сделай текст на русском языке, длиной 3-5 предложений."
        
        response = gigachat_client.chat(
            Chat(messages=[Messages(role=MessagesRole.USER, content=prompt)])
        )
        
        post_text = response.choices[0].message.content
        await message.answer(f"📋 Сгенерированный пост:\n\n{post_text}")
        
    except Exception as e:
        logger.error(f"Ошибка генерации поста: {e}")
        await message.answer("❌ Ошибка при генерации поста")
    
    await state.clear()

# ========== МЕРОПРИЯТИЯ ==========
@dp.message(Command("events"))
async def show_events(message: Message):
    """Показать все мероприятия"""
    events = db.get_events()
    
    if not events:
        await message.answer("📅 Мероприятий пока нет.")
        return
    
    response = "📅 Список мероприятий:\n\n"
    for event in events[-10:]:
        response += f"• {event.get('title', 'Без названия')}\n"
        response += f"  📅 {event.get('date', 'Дата не указана')}\n"
        if event.get('description'):
            response += f"  📝 {event.get('description')[:50]}...\n"
        response += f"  👤 {event.get('creator', 'Неизвестно')}\n\n"
    
    await message.answer(response[:4000])

@dp.message(Command("add_event"))
async def add_event_start(message: Message, state: FSMContext):
    """Начать добавление мероприятия"""
    await message.answer("📝 Введите название мероприятия:")
    await state.set_state(EventStates.waiting_for_title)

@dp.message(EventStates.waiting_for_title)
async def process_event_title(message: Message, state: FSMContext):
    """Обработать название"""
    await state.update_data(title=message.text)
    await message.answer("📄 Введите описание мероприятия:")
    await state.set_state(EventStates.waiting_for_description)

@dp.message(EventStates.waiting_for_description)
async def process_event_description(message: Message, state: FSMContext):
    """Обработать описание"""
    await state.update_data(description=message.text)
    await message.answer("📅 Введите дату мероприятия (например: 25.12.2024):")
    await state.set_state(EventStates.waiting_for_date)

@dp.message(EventStates.waiting_for_date)
async def process_event_date(message: Message, state: FSMContext):
    """Обработать дату и сохранить"""
    data = await state.get_data()
    data["date"] = message.text
    data["creator"] = message.from_user.username or str(message.from_user.id)
    
    event_id = db.add_event(data)
    await message.answer(f"✅ Мероприятие добавлено! ID: {event_id}")
    await state.clear()

@dp.message(Command("delete_event"))
async def delete_event_command(message: Message):
    """Удалить мероприятие"""
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
async def show_media(message: Message):
    """Показать базу СМИ"""
    media_list = db.search_media()
    
    if not media_list:
        await message.answer("📰 База СМИ Саратова пуста.")
        await message.answer("Администратор может добавить СМИ командой: /add_media \"Название\" \"Описание\"")
        return
    
    response = "📰 СМИ Саратова:\n\n"
    for media in media_list:
        response += f"• {media.get('name', 'Неизвестно')}\n"
        if media.get('description'):
            response += f"  {media.get('description')[:80]}...\n"
        response += "\n"
    
    await message.answer(response[:4000])

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

# ========== ПЕРЕЗАПУСК БОТА (BOTHOST API) ==========
@dp.message(Command("restart"))
async def restart_bot_command(message: Message):
    """Перезапустить бота через Bothost API"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Только для администраторов")
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
        logger.error(f"Ошибка перезапуска: {e}")
        await message.answer(f"❌ Ошибка подключения: {str(e)}")

# ========== CALLBACK-QUERY ОБРАБОТЧИКИ ==========
@dp.callback_query(F.data.startswith("admin_"))
async def handle_admin_callback(callback: CallbackQuery):
    """Обработка действий админ-панели"""
    action = callback.data
    
    if action == "admin_stats":
        events_count = len(db.get_events())
        media_count = len(db.search_media())
        await callback.message.answer(
            f"📊 Статистика:\n"
            f"• Мероприятий: {events_count}\n"
            f"• СМИ в базе: {media_count}\n"
            f"• Бот ID: {config.BOT_ID}"
        )
    
    elif action == "admin_events":
        events = db.get_events()
        if events:
            text = "📝 Управление мероприятиями:\n\n"
            text += "/events - список\n"
            text += "/add_event - добавить\n"
            text += "/delete_event <id> - удалить\n\n"
            text += f"Всего мероприятий: {len(events)}"
            await callback.message.answer(text)
        else:
            await callback.message.answer("📅 Мероприятий пока нет. Используйте /add_event")
    
    elif action == "admin_media":
        await callback.message.answer(
            "🏢 Управление СМИ:\n\n"
            "/media - просмотр базы\n"
            "/add_media \"Название\" \"Описание\" - добавить\n\n"
            "Пример: /add_media \"Саратов Сегодня\" \"Главный новостной портал города\""
        )
    
    elif action == "admin_restart":
        keyboard = [[
            types.InlineKeyboardButton(text="✅ Да, перезапустить", callback_data="confirm_restart"),
            types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_restart")
        ]]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        await callback.message.answer("⚠️ Вы уверены, что хотите перезапустить бота?", reply_markup=markup)
    
    await callback.answer()

@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart(callback: CallbackQuery):
    """Подтверждение перезапуска"""
    await restart_bot_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart(callback: CallbackQuery):
    """Отмена перезапуска"""
    await callback.message.edit_text("❌ Перезапуск отменен.")
    await callback.answer()

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска"""
    logger.info("🚀 Запускаю Telegram бота...")
    logger.info(f"🤖 Bot ID: {config.BOT_ID}")
    logger.info(f"👤 User ID: {config.USER_ID}")
    logger.info(f"👑 Admin IDs: {config.ADMIN_IDS}")
    
    try:
        # Запускаем поллинг
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
