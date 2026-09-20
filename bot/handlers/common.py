from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.database.database import AsyncSessionFactory
from bot.database.repositories.content import get_user, upsert_user
from bot.keyboards.main import main_menu


WELCOME_TEXT = (
    "📚 Клуб Романтики\n\n"
    "Добро пожаловать!\n\n"
    "Здесь ты можешь:\n"
    "• найти историю;\n"
    "• посмотреть гайд;\n"
    "• узнать информацию о персонажах;\n"
    "• посмотреть новые обновления;\n"
    "• сохранить любимые истории;\n"
    "• получить уведомления о новом контенте.\n\n"
    "Главное меню:"
)


async def ensure_user_from_message(message: Message):
    if not message.from_user:
        return None
    async with AsyncSessionFactory() as session:
        return await upsert_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )


async def ensure_user_from_callback(callback: CallbackQuery):
    if not callback.from_user:
        return None
    async with AsyncSessionFactory() as session:
        return await upsert_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
        )


async def current_user(telegram_id: int):
    async with AsyncSessionFactory() as session:
        return await get_user(session, telegram_id)


async def show_main(target: Message | CallbackQuery) -> None:
    settings = get_settings()
    is_admin = bool(target.from_user and target.from_user.id in settings.admin_id_set)
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.edit_text(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))
        await target.answer()
    else:
        await target.answer(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))

