from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def guide_filters(
    episode_id: int,
    season_id: int,
    source_url: str | None = None,
    current_page: int = 1,
    total_pages: int = 1,
    filter_name: str = "all",
    next_episode_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    if total_pages > 1:
        prev_cb = f"guide:{episode_id}:{current_page - 1}" if current_page > 1 else "noop"
        next_cb = f"guide:{episode_id}:{current_page + 1}" if current_page < total_pages else "noop"
        rows.append(
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=prev_cb),
                InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"),
                InlineKeyboardButton(text="Вперёд ➡️", callback_data=next_cb),
            ]
        )

    if next_episode_id:
        rows.append(
            [InlineKeyboardButton(text="Следующая серия ➡️", callback_data=f"guide:{next_episode_id}:1")]
        )

    rows.append(
        [
            InlineKeyboardButton(text="🔙 Серии", callback_data=f"episodes:{season_id}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


guide_keyboard = guide_filters


def spoiler_warning(callback_data: str, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, показать", callback_data=callback_data)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback)],
        ]
    )
