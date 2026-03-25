import os
import logging
import sys
from typing import List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ python-dotenv загружен")
except ImportError:
    logger.warning("⚠️ python-dotenv не установлен")

class Config:
    TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        logger.error("❌ Не найден BOT_TOKEN!")
        raise ValueError("Установите BOT_TOKEN")
    
    BOT_ID = os.getenv('BOT_ID', '')
    USER_ID = os.getenv('USER_ID', '')
    DOMAIN = os.getenv('DOMAIN', '')
    PORT = int(os.getenv('PORT', '3000'))
    
    # GigaChat API
    GIGACHAT_CLIENT_ID = "019b2405-4854-7d29-9a54-938aa6fff638"
    GIGACHAT_SECRET = "dc515277-136b-41b9-b5e4-dcad944bb94b"
    
    # ID админов — ИСПРАВЛЕНО!
    ADMIN_IDS = [671065514]  # Ваш ID напрямую
    
    @staticmethod
    def get_agent_url():
        return os.getenv('BOTHOST_AGENT_URL', 'http://agent:8000')

config = Config()
logger.info(f"✅ Конфигурация загружена")
logger.info(f"👑 Admin IDs: {config.ADMIN_IDS}")
