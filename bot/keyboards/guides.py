from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


FILTERS = {
    "all": "🧭 Все",
    "diamond": "💎 Алмазы",
    "romance": "❤️ Романтика",
    "parameter": "📊 Параметры",
    "critical": "⚠️ Критичные",
}


def guide_filters(
    episode_id: int,
    season_id: int,
    source_url: str | None = None,
    current_page: int = 1,
    total_pages: int = 1,
    filter_name: str = "all",
) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        prev_cb = f"guide:{episode_id}:{filter_name}:{current_page - 1}" if current_page > 1 else "noop"
        next_cb = f"guide:{episode_id}:{filter_name}:{current_page + 1}" if current_page < total_pages else "noop"
        rows.append(
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=prev_cb),
                InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"),
                InlineKeyboardButton(text="Вперёд ➡️", callback_data=next_cb),
            ]
        )

    for key, title in FILTERS.items():
        prefix = "✅ " if key == filter_name else ""
        rows.append([InlineKeyboardButton(text=f"{prefix}{title}", callback_data=f"guide:{episode_id}:{key}:1")])

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
