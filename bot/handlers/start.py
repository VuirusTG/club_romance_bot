from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message, show_main
from bot.keyboards.main import home_back
from bot.utils.formatting import help_text, story_text


router = Router(name="start")


async def _open_deep_link(message: Message, payload: str) -> bool:
    if not message.from_user or "_" not in payload:
        return False
    kind, raw_id = payload.split("_", 1)
    if not raw_id.isdigit():
        return False

    async with AsyncSessionFactory() as session:
        if kind == "story":
            story = await content.get_story(session, int(raw_id))
            if story:
                from bot.keyboards.stories import story_card

                await message.answer(story_text(story), reply_markup=story_card(story.id))
                return True
        if kind == "guide":
            episode = await content.get_episode_with_choices(session, int(raw_id))
            user = await content.get_user(session, message.from_user.id)
            if episode and user:
                from bot.keyboards.guides import guide_filters
                from bot.utils.formatting import paginate_episode_guide

                choices = sorted(episode.choices, key=lambda item: item.order_index)
                guide_text, current_page, total_pages = paginate_episode_guide(
                    episode, choices, user.spoiler_level, filter_name="all", page=1
                )
                await message.answer(
                    guide_text,
                    reply_markup=guide_filters(
                        episode.id,
                        episode.season_id,
                        episode.guide_source_url,
                        current_page=current_page,
                        total_pages=total_pages,
                        filter_name="all",
                    ),
                )
                return True
        if kind == "character":
            character = await content.get_character(session, int(raw_id))
            user = await content.get_user(session, message.from_user.id)
            if character and user:
                from bot.keyboards.main import back_home
                from bot.utils.formatting import character_text

                await message.answer(character_text(character, user.spoiler_level), reply_markup=back_home(f"chars:{character.story_id}"))
                return True
    return False


@router.message(Command("start"))
async def start_command(message: Message, command: CommandObject) -> None:
    await ensure_user_from_message(message)
    payload = (command.args or "").strip()
    if payload and await _open_deep_link(message, payload):
        return
    await show_main(message)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await ensure_user_from_message(message)
    await message.answer(help_text(), reply_markup=home_back())


@router.callback_query(F.data == "main")
async def main_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    await show_main(callback)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    if callback.message:
        await callback.message.edit_text(help_text(), reply_markup=home_back())
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
