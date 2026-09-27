from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message
from bot.keyboards.main import home_back


router = Router(name="favorites")


async def _favorites_payload(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionFactory() as session:
        items = await content.list_favorites_detailed(session, user_id)

    if not items:
        return (
            "⭐ <b>Моё избранное</b>\n\n"
            "Пока пусто. Добавляй любимые истории, персонажей и серии кнопкой ⭐.",
            home_back(),
        )

    text = (
        "⭐ <b>Моё избранное</b>\n\n"
        "Нажми на элемент для перехода или на ❌, чтобы удалить из избранного:"
    )
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(text=item["display"], callback_data=item["callback_data"]),
                InlineKeyboardButton(text="❌", callback_data=item["delete_callback"]),
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _subscriptions_payload(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionFactory() as session:
        subscriptions = await content.list_user_subscriptions(session, user_id)

    if not subscriptions:
        return (
            "🔔 <b>Мои подписки</b>\n\n"
            "У тебя пока нет активных подписок.\n\n"
            "Чтобы получать уведомления о выходе новых серий и гайдов, открой карточку истории и нажми кнопку «🔔 Подписка».",
            home_back(),
        )

    text = (
        "🔔 <b>Мои подписки</b>\n\n"
        "Ты подписан на обновления следующих историй:\n\n"
        "Нажми на историю для перехода или на 🔕, чтобы отключить подписку:"
    )
    rows: list[list[InlineKeyboardButton]] = []
    for _sub, story in subscriptions:
        rows.append(
            [
                InlineKeyboardButton(text=f"📖 {story.title}", callback_data=f"story:{story.id}"),
                InlineKeyboardButton(text="🔕 Отключить", callback_data=f"sub_off:{story.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("favorites"))
async def favorites_command(message: Message) -> None:
    user = await ensure_user_from_message(message)
    if user:
        text, kb = await _favorites_payload(user.id)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "favorites")
async def favorites_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if callback.message and user:
        text, kb = await _favorites_payload(user.id)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("fav_del:"))
async def favorite_delete_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if not user or not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) == 3:
        _, item_type, item_id_str = parts
        try:
            item_id = int(item_id_str)
            async with AsyncSessionFactory() as session:
                await content.remove_favorite(session, user.id, item_type, item_id)
            await callback.answer("Удалено из избранного", show_alert=False)
        except ValueError:
            await callback.answer()
            return
    if callback.message:
        text, kb = await _favorites_payload(user.id)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "subscriptions")
async def subscriptions_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if callback.message and user:
        text, kb = await _subscriptions_payload(user.id)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub_off:"))
async def subscription_off_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if not user or not callback.data:
        await callback.answer()
        return
    try:
        story_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            await content.disable_subscription(session, user.id, story_id)
        await callback.answer("Подписка отключена", show_alert=False)
    except (IndexError, ValueError):
        await callback.answer()
        return
    if callback.message:
        text, kb = await _subscriptions_payload(user.id)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
