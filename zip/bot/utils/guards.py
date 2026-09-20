from aiogram.types import CallbackQuery, Message


async def deny_not_admin(event: CallbackQuery | Message) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer("Недостаточно прав.", show_alert=True)
    else:
        await event.answer("Недостаточно прав.")

