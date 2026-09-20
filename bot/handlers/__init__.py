from aiogram import Dispatcher

from bot.handlers import admin, characters, favorites, search, settings, start, stories, updates


def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(start.router)
    dispatcher.include_router(stories.router)
    dispatcher.include_router(characters.router)
    dispatcher.include_router(favorites.router)
    dispatcher.include_router(updates.router)
    dispatcher.include_router(settings.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(search.router)

