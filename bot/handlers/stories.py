import math

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback
from bot.keyboards.guides import guide_filters
from bot.keyboards.main import back_home
from bot.keyboards.stories import episodes_list, seasons_list, stories_page, story_card
from bot.utils.formatting import episode_guide_text, paginate_episode_guide, story_text


router = Router(name="stories")


def _filter_choices(choices, filter_name: str):
    ordered = sorted(choices, key=lambda item: item.order_index)
    if filter_name == "diamond":
        return [choice for choice in ordered if choice.cost_diamonds > 0]
    if filter_name == "romance":
        return [choice for choice in ordered if "romance" in choice.tags or "роман" in choice.tags.lower()]
    if filter_name == "parameter":
        return [choice for choice in ordered if choice.parameter_changes]
    if filter_name == "critical":
        return [choice for choice in ordered if choice.is_critical]
    return ordered


@router.callback_query(F.data.startswith("stories:p:"))
async def stories_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    page = int(callback.data.rsplit(":", 1)[1])
    async with AsyncSessionFactory() as session:
        stories, total_pages = await content.list_stories(session, page)
    if callback.message:
        await callback.message.edit_text(
            f"📖 Истории — страница {page}/{total_pages}\n\nВыбери историю:",
            reply_markup=stories_page(stories, page, total_pages),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("story:"))
async def story_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    story_id = int(callback.data.split(":", 1)[1])
    async with AsyncSessionFactory() as session:
        story = await content.get_story(session, story_id)
    if not story:
        await callback.answer("История не найдена.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text(story_text(story), reply_markup=story_card(story.id))
    await callback.answer()


@router.callback_query(F.data.startswith("seasons:"))
async def seasons_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    story_id = int(callback.data.split(":", 1)[1])
    async with AsyncSessionFactory() as session:
        seasons = await content.list_seasons(session, story_id)
    text = "📚 Сезоны\n\nВыбери сезон:" if seasons else "Для этой истории сезоны пока не добавлены."
    markup = seasons_list(story_id, seasons) if seasons else back_home(f"story:{story_id}")
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("episodes:"))
async def episodes_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    parts = callback.data.split(":")
    season_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

    async with AsyncSessionFactory() as session:
        season = await content.get_season(session, season_id)
        all_episodes = await content.list_episodes(session, season_id)
    if not season:
        await callback.answer("Сезон не найден.", show_alert=True)
        return

    PAGE_SIZE = 10
    total_episodes = len(all_episodes)
    total_pages = max(1, math.ceil(total_episodes / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * PAGE_SIZE
    page_episodes = all_episodes[start_idx : start_idx + PAGE_SIZE]

    season_label = season.title if (season.title and "том" in season.title.lower()) else f"Сезон {season.number}"
    if not all_episodes:
        text = f"В этом {'томе' if 'том' in season_label.lower() else 'сезоне'} пока нет серий."
    elif total_pages > 1:
        text = f"🎬 {season_label} (страница {page}/{total_pages})\n\nВыбери серию:"
    else:
        text = f"🎬 {season_label}\n\nВыбери серию:"

    markup = episodes_list(season.story_id, season_id, page_episodes, page=page, total_pages=total_pages)
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
    await callback.answer()


@router.callback_query(F.data.startswith("guide:"))
async def guide_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    parts = callback.data.split(":")
    episode_id = int(parts[1])
    filter_name = parts[2] if len(parts) > 2 else "all"
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1

    async with AsyncSessionFactory() as session:
        episode = await content.get_episode_with_choices(session, episode_id)
        if episode and user:
            await content.save_progress(session, user.id, episode.season.story_id, episode.season_id, episode.id)
    if not episode or not user:
        await callback.answer("Серия не найдена.", show_alert=True)
        return

    choices = _filter_choices(episode.choices, filter_name)
    guide_text, current_page, total_pages = paginate_episode_guide(
        episode, choices, user.spoiler_level, filter_name=filter_name, page=page
    )
    markup = guide_filters(
        episode.id,
        episode.season_id,
        episode.guide_source_url,
        current_page=current_page,
        total_pages=total_pages,
        filter_name=filter_name,
    )
    if callback.message:
        try:
            await callback.message.edit_text(guide_text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
    await callback.answer()


@router.callback_query(F.data.startswith("diamonds:"))
async def diamonds_callback(callback: CallbackQuery) -> None:
    await ensure_user_from_callback(callback)
    episode_id = int(callback.data.split(":", 1)[1])
    async with AsyncSessionFactory() as session:
        episode = await content.get_episode_with_choices(session, episode_id)
    if not episode:
        await callback.answer("Серия не найдена.", show_alert=True)
        return
    required = sum(choice.cost_diamonds for choice in episode.choices if choice.is_critical)
    recommended = sum(choice.cost_diamonds for choice in episode.choices if choice.cost_diamonds and ("romance" in choice.tags or choice.is_critical))
    maximum = sum(choice.cost_diamonds for choice in episode.choices)
    text = (
        f"💎 Экономия алмазов\n\n"
        f"Серия {episode.number}\n\n"
        f"Обязательно: {required} 💎\n"
        f"Рекомендуется: {recommended} 💎\n"
        f"Максимальный маршрут: {maximum} 💎\n\n"
        "Платные выборы с важным влиянием помечены в гайде как критичные или романтические."
    )
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=guide_filters(episode.id, episode.season_id, episode.guide_source_url))
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
    await callback.answer()


@router.callback_query(F.data.startswith("fav:story:"))
async def favorite_story_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    story_id = int(callback.data.rsplit(":", 1)[1])
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        enabled = await content.toggle_favorite(session, user.id, "story", story_id)
    await callback.answer("Добавлено в избранное." if enabled else "Удалено из избранного.")


@router.callback_query(F.data.startswith("sub:"))
async def subscription_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    story_id = int(callback.data.split(":", 1)[1])
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        enabled = await content.toggle_subscription(session, user.id, story_id)
    await callback.answer("Подписка включена." if enabled else "Подписка отключена.")
