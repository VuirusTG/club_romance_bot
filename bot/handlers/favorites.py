from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message
from bot.keyboards.main import home_back


router = Router(name="favorites")


async def _favorites_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        favorites = await content.list_favorites(session, user_id)
    if not favorites:
        return "⭐ Моё избранное\n\nПока пусто. Добавляй истории и персонажей кнопкой ⭐."
    lines = ["⭐ Моё избранное", ""]
    for favorite in favorites:
        icon = {"story": "📖", "character": "👤", "episode": "🧭"}.get(favorite.item_type, "⭐")
        lines.append(f"{icon} {favorite.item_type} #{favorite.item_id}")
    return "\n".join(lines)


@router.message(Command("favorites"))
async def favorites_command(message: Message) -> None:
    user = await ensure_user_from_message(message)
    if user:
        await message.answer(await _favorites_text(user.id), reply_markup=home_back())


@router.callback_query(F.data == "favorites")
async def favorites_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if callback.message and user:
        await callback.message.edit_text(await _favorites_text(user.id), reply_markup=home_back())
    await callback.answer()


@router.callback_query(F.data == "subscriptions")
async def subscriptions_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    if callback.message:
        await callback.message.edit_text(
            "🔔 Подписки\n\nОткрой карточку истории и нажми «Подписка», чтобы получать уведомления о новых сериях и гайдах.",
            reply_markup=home_back(),
        )
    await callback.answer()

