import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.database.database import init_db
from bot.handlers import register_handlers
from bot.utils.logger import setup_logging


async def handle_root(request: web.Request) -> web.Response:
    html = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Клуб Романтики — Telegram Bot</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121214; color: #f0f0f5; text-align: center; padding: 60px 20px; }
        .card { max-width: 500px; margin: 0 auto; background: #1f1f23; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ff5277; margin-bottom: 8px; }
        .badge { display: inline-block; padding: 6px 14px; border-radius: 20px; background: #10b981; color: #fff; font-weight: bold; font-size: 14px; margin-top: 10px; }
        p { color: #a1a1aa; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Клуб Романтики</h1>
        <p>Интерактивный путеводитель и база гайдов Telegram</p>
        <span class="badge">● Bot Online</span>
        <p style="margin-top: 25px; font-size: 13px;">58 историй • 144 сезона • 1 613 серий • 53 236 выборов</p>
    </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "healthy",
        "service": "club-romance-bot",
        "stories": 58,
        "seasons": 144,
        "episodes": 1613,
        "choices": 53236,
    })


async def start_web_server(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.getLogger(__name__).info(f"Health-check web server listening on 0.0.0.0:{port}")
    return runner


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    await init_db()

    web_runner = None
    if settings.enable_web:
        try:
            web_runner = await start_web_server(settings.port)
        except Exception as e:
            logger.warning(f"Could not start web server on port {settings.port}: {e}")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    register_handlers(dispatcher)

    logger.info("Club Romance bot started")
    try:
        await dispatcher.start_polling(bot)
    finally:
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
