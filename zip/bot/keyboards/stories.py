from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import Episode, Season, Story


def stories_page(stories: list[Story], page: int, total_pages: int, prefix: str = "story") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📖 {story.title}", callback_data=f"{prefix}:{story.id}")] for story in stories]
    rows.append(
        [
            InlineKeyboardButton(text="⬅️", callback_data=f"stories:p:{max(1, page - 1)}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"stories:p:{min(total_pages, page + 1)}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🔎 Поиск", callback_data="search:start"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def story_card(story_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Гайд", callback_data=f"seasons:{story_id}"),
                InlineKeyboardButton(text="👥 Персонажи", callback_data=f"chars:{story_id}"),
            ],
            [
                InlineKeyboardButton(text="📚 Сезоны", callback_data=f"seasons:{story_id}"),
                InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav:story:{story_id}"),
            ],
            [
                InlineKeyboardButton(text="🔔 Подписка", callback_data=f"sub:{story_id}"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="stories:p:1"),
            ],
        ]
    )


def seasons_list(story_id: int, seasons: list[Season]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📚 Сезон {season.number}", callback_data=f"episodes:{season.id}")] for season in seasons]
    rows.append(
        [
            InlineKeyboardButton(text="🔙 История", callback_data=f"story:{story_id}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def episodes_list(story_id: int, season_id: int, episodes: list[Episode]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎬 Серия {episode.number}: {episode.title or 'Без названия'}",
                callback_data=f"guide:{episode.id}:all",
            )
        ]
        for episode in episodes
    ]
    rows.append(
        [
            InlineKeyboardButton(text="🔙 Сезоны", callback_data=f"seasons:{story_id}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

