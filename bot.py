import asyncio
import sys
import traceback

# Импортируем конфиг для инициализации логгера
from config import logger, config
from bot_main import dp, bot

async def main():
    logger.info("🤖 Запускаю Telegram бота...")
    logger.info(f"🔧 Конфигурация: BOT_ID={config.BOT_ID}, DOMAIN={config.DOMAIN}")
    
    try:
        # Запускаем поллинг
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
