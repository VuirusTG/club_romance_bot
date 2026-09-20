from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database.database import AsyncSessionFactory
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message


router = Router(name="settings")


def _settings_keyboard(notifications_enabled: bool) -> InlineKeyboardMarkup:
    notification_label = "🔕 Отключить уведомления" if notifications_enabled else "🔔 Включить уведомления"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=notification_label, callback_data="settings:notifications")],
            [InlineKeyboardButton(text="🟢 Без спойлеров", callback_data="settings:spoiler:0")],
            [InlineKeyboardButton(text="🟡 Небольшие спойлеры", callback_data="settings:spoiler:1")],
            [InlineKeyboardButton(text="🔴 Все спойлеры", callback_data="settings:spoiler:2")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main")],
        ]
    )


@router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    user = await ensure_user_from_message(message)
    if user:
        await message.answer("⚙️ Настройки", reply_markup=_settings_keyboard(user.notifications_enabled))


@router.callback_query(F.data == "settings")
async def settings_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if callback.message and user:
        await callback.message.edit_text("⚙️ Настройки", reply_markup=_settings_keyboard(user.notifications_enabled))
    await callback.answer()


@router.callback_query(F.data == "settings:notifications")
async def notifications_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        enabled = await content.toggle_notifications(session, user.id)
    if callback.message:
        await callback.message.edit_text("⚙️ Настройки", reply_markup=_settings_keyboard(enabled))
    await callback.answer("Уведомления включены." if enabled else "Уведомления отключены.")


@router.callback_query(F.data.startswith("settings:spoiler:"))
async def spoiler_callback(callback: CallbackQuery) -> None:
    user = await ensure_user_from_callback(callback)
    level = int(callback.data.rsplit(":", 1)[1])
    if user:
        async with AsyncSessionFactory() as session:
            await content.set_spoiler_level(session, user.id, level)
    await callback.answer("Настройки спойлеров обновлены.")

