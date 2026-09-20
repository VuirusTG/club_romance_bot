from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.database.database import AsyncSessionFactory
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message
from bot.keyboards.main import home_back
from bot.services.search_service import format_search_results
from bot.states.states import state_storage


router = Router(name="search")


@router.message(Command("search"))
async def search_command(message: Message) -> None:
    await ensure_user_from_message(message)
    if message.from_user:
        state_storage.set(message.from_user.id, "search")
    await message.answer("🔎 Поиск\n\nВведи название истории, имя персонажа или ключевое слово.", reply_markup=home_back())


@router.callback_query(F.data == "search:start")
async def search_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    state_storage.set(callback.from_user.id, "search")
    if callback.message:
        await callback.message.edit_text("🔎 Поиск\n\nВведи название истории, имя персонажа или ключевое слово.", reply_markup=home_back())
    await callback.answer()


@router.message(F.text)
async def text_state_handler(message: Message) -> None:
    if not message.from_user or not message.text or message.text.startswith("/"):
        return
    state = state_storage.get(message.from_user.id)
    if not state or state.name != "search":
        return
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Введи хотя бы 2 символа.")
        return
    await ensure_user_from_message(message)
    async with AsyncSessionFactory() as session:
        text = await format_search_results(session, query)
    state_storage.clear(message.from_user.id)
    await message.answer(text, reply_markup=home_back())

