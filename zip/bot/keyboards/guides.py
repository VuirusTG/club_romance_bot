from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


FILTERS = {
    "all": "🧭 Все",
    "diamond": "💎 Алмазы",
    "romance": "❤️ Романтика",
    "parameter": "📊 Параметры",
    "critical": "⚠️ Критичные",
}


def guide_filters(episode_id: int, season_id: int, source_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"guide:{episode_id}:{key}")] for key, title in FILTERS.items()]
    rows.append([InlineKeyboardButton(text="💎 Экономия алмазов", callback_data=f"diamonds:{episode_id}")])
    if source_url:
        rows.append([InlineKeyboardButton(text="🔗 Открыть источник гайда", url=source_url)])
    rows.append(
        [
            InlineKeyboardButton(text="🔙 Серии", callback_data=f"episodes:{season_id}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def spoiler_warning(callback_data: str, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, показать", callback_data=callback_data)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback)],
        ]
    )
