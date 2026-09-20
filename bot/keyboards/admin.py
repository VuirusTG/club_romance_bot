from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Истории", callback_data="admin:stories")],
            [InlineKeyboardButton(text="➕ Добавить историю", callback_data="admin:add_story")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main")],
        ]
    )


def admin_stories(story_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:delete_story:{story_id}")],
            [InlineKeyboardButton(text="🔙 Админ", callback_data="admin")],
        ]
    )

