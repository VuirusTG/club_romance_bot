import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Subscription, User

logger = logging.getLogger(__name__)


async def notify_story_subscribers(bot: Bot, session: AsyncSession, story_id: int, text: str) -> int:
    statement = (
        select(User.telegram_id)
        .join(Subscription, Subscription.user_id == User.id)
        .where(
            Subscription.story_id == story_id,
            Subscription.is_enabled.is_(True),
            User.notifications_enabled.is_(True),
        )
    )
    sent = 0
    for telegram_id in (await session.scalars(statement)).all():
        try:
            await bot.send_message(telegram_id, text)
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after + 1)
        except TelegramAPIError:
            logger.warning("Failed to send notification to user_id=%s", telegram_id, exc_info=True)
    return sent

