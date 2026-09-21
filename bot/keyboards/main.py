from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📖 Истории", callback_data="stories:p:1"),
        ],
        [
            InlineKeyboardButton(text="👤 Персонажи", callback_data="char_stories"),
            InlineKeyboardButton(text="🆕 Обновления", callback_data="updates"),
        ],
        [
            InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites"),
            InlineKeyboardButton(text="🔎 Поиск", callback_data="search:start"),
        ],
        [
            InlineKeyboardButton(text="🔔 Подписки", callback_data="subscriptions"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")]]
    )


def back_home(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback),
                InlineKeyboardButton(text="🏠 Меню", callback_data="main"),
            ]
        ]
    )

