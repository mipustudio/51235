import os
import logging
import sys
from typing import List

# Настраиваем логгирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ python-dotenv загружен успешно")
except ImportError as e:
    logger.error(f"❌ python-dotenv не установлен: {e}")
    logger.info("⚠️ Используем переменные окружения напрямую")

class Config:
    # Получаем токен из переменных окружения Bothost
    TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN в переменных окружения!")
        logger.error("Доступные переменные: " + ", ".join(os.environ.keys()))
        raise ValueError("Установите BOT_TOKEN в настройках Bothost")
    
    # Переменные Bothost
    BOT_ID = os.getenv('BOT_ID', '')
    USER_ID = os.getenv('USER_ID', '')
    DOMAIN = os.getenv('DOMAIN', '')
    PORT = int(os.getenv('PORT', '3000'))
    
    # GigaChat API (установите в настройках бота на Bothost)
    GIGACHAT_CLIENT_ID = os.getenv('019b2405-4854-7d29-9a54-938aa6fff638', '')
    GIGACHAT_SECRET = os.getenv('dc515277-136b-41b9-b5e4-dcad944bb94b', '')
    
    # Получаем ID админов из переменной окружения
    admin_ids_str = os.getenv('ADMIN_IDS', '')
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
    
    # URL для API Bothost
    @staticmethod
    def get_agent_url():
        """Определяет URL API Bothost"""
        # Используем переменную окружения или дефолтное значение
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

# Создаем экземпляр конфига
config = Config()

# Логируем успешную загрузку конфига
logger.info(f"✅ Конфигурация загружена")
logger.info(f"🤖 Bot ID: {config.BOT_ID}")
logger.info(f"👤 User ID: {config.USER_ID}")
logger.info(f"👑 Admin IDs: {config.ADMIN_IDS}")
logger.info(f"🌐 Domain: {config.DOMAIN}")
logger.info(f"🔌 Port: {config.PORT}")
