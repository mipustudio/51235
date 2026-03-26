import asyncio
from io import BytesIO
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile, BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import config, logger

# Проверяем доступность PIL
PIL_AVAILABLE = False
try:
    from PIL import Image
    PIL_AVAILABLE = True
    logger.info("✅ PIL/Pillow доступен для обработки изображений")
except ImportError as e:
    logger.warning(f"⚠️ PIL не установлен: {e}")

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=config.TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Путь к логотипу
LOGO_PATH = Path(__file__).parent / "logo.png"


def create_main_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт главную клавиатуру с одной кнопкой"""
    keyboard = [[KeyboardButton(text="🖼️ Добавить логотип на фото")]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ========== КОМАНДЫ ==========
@dp.message(CommandStart())
async def start_command(message: Message):
    """Обработка команды /start"""
    welcome_text = """
🤖 Бот для добавления логотипа на фото

Нажмите кнопку ниже или отправьте фото, чтобы добавить логотип.
"""
    await message.answer(welcome_text, reply_markup=create_main_keyboard())


# ========== ОБРАБОТКА ФОТО ==========
@dp.message(F.photo)
async def process_photo(message: Message):
    """Обработка фото — добавление логотипа справа сверху"""
    if not PIL_AVAILABLE:
        await message.answer("❌ Обработка фото недоступна. Установите Pillow: pip install Pillow")
        return

    if not LOGO_PATH.exists():
        await message.answer("❌ Файл логотипа не найден. Поместите logo.png в папку с ботом.")
        return

    try:
        processing_msg = await message.answer("🔄 Обрабатываю фото...")

        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)

        # Открываем изображение
        image = Image.open(BytesIO(photo_bytes.read())).convert("RGBA")

        # Открываем и подготавливаем логотип
        logo = Image.open(LOGO_PATH).convert("RGBA")

        # Вычисляем размер логотипа (15% от ширины фото)
        logo_width = int(image.width * 0.15)
        logo_ratio = logo.width / logo.height
        logo_height = int(logo_width / logo_ratio)

        # Уменьшаем логотип
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

        # Позиция: справа сверху (отступ 20px)
        padding = 20
        x = image.width - logo_width - padding
        y = padding

        # Создаём прозрачный слой для логотипа
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        overlay.paste(logo, (x, y))

        # Накладываем логотип на изображение
        result = Image.alpha_composite(image, overlay)

        # Сохраняем в JPEG (конвертируем в RGB)
        result_rgb = result.convert("RGB")
        output = BytesIO()
        result_rgb.save(output, format="JPEG", quality=90)
        output.seek(0)

        await bot.send_photo(
            chat_id=message.chat.id,
            photo=BufferedInputFile(output.getvalue(), filename="logo_photo.jpg"),
            reply_to_message_id=message.message_id
        )

        await processing_msg.delete()

    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await message.answer(f"❌ Ошибка обработки: {e}")


# ========== ЗАПУСК ==========
async def set_webhook(bot: Bot):
    """Устанавливает вебхук для Bothost"""
    webhook_url = config.get_webhook_url()
    await bot.set_webhook(webhook_url)
    logger.info(f"✅ Вебхук установлен: {webhook_url}")


async def on_startup(bot: Bot):
    """Запускается при старте приложения"""
    logger.info("🚀 Запуск бота...")
    await set_webhook(bot)

    # Устанавливаем команды бота
    commands = [
        BotCommand(command="start", description="Запустить бота"),
    ]
    await bot.set_my_commands(commands)


def create_web_app():
    """Создаёт веб-приложение для Bothost"""
    app = web.Application()

    # Настраиваем вебхук
    SimpleRequestHandler(dp, bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    return app


async def main():
    """Запуск бота"""
    if config.BOT_ID:
        # Запуск через вебхук (Bothost)
        app = create_web_app()

        # Устанавливаем онстартап коллбэк
        app.on_startup.append(on_startup)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
        await site.start()

        logger.info(f"🌐 Бот запущен на порту {config.PORT}")
        logger.info(f"🔗 Вебхук URL: {config.get_webhook_url()}")

        # Держим приложение запущенным
        while True:
            await asyncio.sleep(3600)
    else:
        # Запуск через polling (локальная разработка)
        await bot.delete_webhook()
        logger.info("🚀 Запуск бота в режиме polling...")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
