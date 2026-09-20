from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message


router = Router(name="updates")


def _updates_keyboard(posts) -> InlineKeyboardMarkup:
    rows = []
    for post in posts:
        if post.source_url:
            rows.append([InlineKeyboardButton(text=f"🔗 Источник: {post.source_name or 'официально'}", url=post.source_url)])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _updates_payload():
    async with AsyncSessionFactory() as session:
        posts = await content.list_updates(session)
    if not posts:
        return "🆕 Обновления игры\n\nОфициальных новостей пока нет.", InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")]]
        )

    lines = ["🆕 Обновления игры «Клуб Романтики»", ""]
    for post in posts:
        lines.append(f"📅 {post.created_at:%d.%m.%Y}")
        if post.game_version:
            lines.append(f"📱 Версия: {post.game_version}")
        lines.append(f"📢 {post.title}")
        lines.append(post.body)
        if post.source_name:
            lines.append(f"Источник: {post.source_name}")
        lines.append("")
    return "\n".join(lines).strip(), _updates_keyboard(posts)


@router.message(Command("updates"))
async def updates_command(message: Message) -> None:
    await ensure_user_from_message(message)
    text, keyboard = await _updates_payload()
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "updates")
async def updates_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    text, keyboard = await _updates_payload()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

