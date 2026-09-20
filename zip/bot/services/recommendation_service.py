from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Story


async def recommendations(session: AsyncSession, limit: int = 5) -> list[Story]:
    return list((await session.scalars(select(Story).where(Story.is_published.is_(True)).order_by(Story.views_count.desc(), Story.title).limit(limit))).all())

