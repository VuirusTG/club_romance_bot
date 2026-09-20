from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback
from bot.keyboards.main import back_home
from bot.keyboards.stories import stories_page
from bot.utils.formatting import character_text


router = Router(name="characters")


@router.callback_query(F.data == "char_stories")
async def character_stories_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    async with AsyncSessionFactory() as session:
        stories, total_pages = await content.list_stories(session, 1)
    if callback.message:
        await callback.message.edit_text(
            "👤 Персонажи\n\nСначала выбери историю:",
            reply_markup=stories_page(stories, 1, total_pages, prefix="chars"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("chars:"))
async def characters_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    story_id = int(callback.data.split(":", 1)[1])
    async with AsyncSessionFactory() as session:
        characters = await content.list_characters(session, story_id)
    rows = [[InlineKeyboardButton(text=f"👤 {character.name}", callback_data=f"char:{character.id}")] for character in characters]
    rows.append(
        [
            InlineKeyboardButton(text="🔙 История", callback_data=f"story:{story_id}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    text = "👤 Персонажи\n\nВыбери персонажа:" if characters else "Персонажи для этой истории пока не добавлены."
    if callback.message:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("char:"))
async def character_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    character_id = int(callback.data.split(":", 1)[1])
    async with AsyncSessionFactory() as session:
        character = await content.get_character(session, character_id)
    if not character or not user:
        await callback.answer("Персонаж не найден.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text(
            character_text(character, user.spoiler_level),
            reply_markup=back_home(f"chars:{character.story_id}"),
        )
    await callback.answer()

