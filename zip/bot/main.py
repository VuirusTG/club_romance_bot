import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.database.database import init_db
from bot.handlers import register_handlers
from bot.utils.logger import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    register_handlers(dispatcher)

    logging.getLogger(__name__).info("Club Romance bot started")
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

