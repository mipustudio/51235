import os
import logging
from typing import List
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    # Получаем токен из переменных окружения Bothost
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN в переменных окружения!")
        raise ValueError("Установите BOT_TOKEN в настройках Bothost")
    
    # Переменные Bothost
    BOT_ID = os.getenv('BOT_ID')
    USER_ID = os.getenv('USER_ID')
    DOMAIN = os.getenv('DOMAIN', '')
    PORT = int(os.getenv('PORT', 3000))
    
    # GigaChat API (установите в настройках бота на Bothost)
    GIGACHAT_CLIENT_ID = os.getenv('019b2405-4854-7d29-9a54-938aa6fff638', '')
    GIGACHAT_SECRET = os.getenv('dc515277-136b-41b9-b5e4-dcad944bb94b', '')
    
    # Получаем ID админов из переменной окружения
    admin_ids_str = os.getenv('ADMIN_IDS', '')
    ADMIN_IDS = [int(id_.strip()) for id_ in admin_ids_str.split(",") if id_.strip()]
    
    # URL для API Bothost (автоматическое определение)
    @staticmethod
    def get_agent_url():
        """Определяет URL API Bothost"""
        # Сначала пробуем внутренний URL Docker
        internal_url = "http://agent:8000"
        external_url = os.getenv('BOTHOST_AGENT_URL', 'http://agent.bothost.ru')
        return internal_url  # Bothost рекомендует использовать внутренний URL

config = Config()