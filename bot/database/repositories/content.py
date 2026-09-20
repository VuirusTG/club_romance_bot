from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import (
    Character,
    Choice,
    Episode,
    Favorite,
    Progress,
    Season,
    Story,
    Subscription,
    UpdatePost,
    User,
)


PAGE_SIZE = 5


async def upsert_user(session: AsyncSession, telegram_id: int, username: str | None, first_name: str | None) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_active_at=datetime.utcnow(),
        )
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.last_active_at = datetime.utcnow()
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def set_spoiler_level(session: AsyncSession, user_id: int, level: int) -> None:
    await session.execute(update(User).where(User.id == user_id).values(spoiler_level=level))
    await session.commit()


async def toggle_notifications(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is None:
        return False
    user.notifications_enabled = not user.notifications_enabled
    await session.commit()
    return user.notifications_enabled


async def list_stories(session: AsyncSession, page: int = 1, query: str | None = None) -> tuple[list[Story], int]:
    filters = [Story.is_published.is_(True)]
    if query:
        filters.append(Story.title.ilike(f"%{query}%"))
    total = await session.scalar(select(func.count(Story.id)).where(*filters))
    statement = (
        select(Story)
        .where(*filters)
        .order_by(Story.title)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    stories = list((await session.scalars(statement)).all())
    total_pages = max(1, ((total or 0) + PAGE_SIZE - 1) // PAGE_SIZE)
    return stories, total_pages


async def get_story(session: AsyncSession, story_id: int) -> Story | None:
    story = await session.scalar(
        select(Story)
        .options(selectinload(Story.seasons).selectinload(Season.episodes), selectinload(Story.characters))
        .where(Story.id == story_id)
    )
    if story:
        story.views_count += 1
        await session.commit()
    return story


async def list_seasons(session: AsyncSession, story_id: int) -> list[Season]:
    return list((await session.scalars(select(Season).where(Season.story_id == story_id).order_by(Season.number))).all())


async def get_season(session: AsyncSession, season_id: int) -> Season | None:
    return await session.get(Season, season_id)


async def list_episodes(session: AsyncSession, season_id: int) -> list[Episode]:
    return list(
        (
            await session.scalars(
                select(Episode)
                .where(Episode.season_id == season_id, Episode.is_published.is_(True))
                .order_by(Episode.number)
            )
        ).all()
    )


async def get_episode_with_choices(session: AsyncSession, episode_id: int) -> Episode | None:
    return await session.scalar(
        select(Episode)
        .options(selectinload(Episode.choices), selectinload(Episode.season).selectinload(Season.story))
        .where(Episode.id == episode_id)
    )


async def list_characters(session: AsyncSession, story_id: int) -> list[Character]:
    return list((await session.scalars(select(Character).where(Character.story_id == story_id).order_by(Character.name))).all())


async def get_character(session: AsyncSession, character_id: int) -> Character | None:
    return await session.scalar(
        select(Character).options(selectinload(Character.story)).where(Character.id == character_id)
    )


async def toggle_favorite(session: AsyncSession, user_id: int, item_type: str, item_id: int) -> bool:
    favorite = await session.scalar(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.item_type == item_type,
            Favorite.item_id == item_id,
        )
    )
    if favorite:
        await session.delete(favorite)
        await session.commit()
        return False
    session.add(Favorite(user_id=user_id, item_type=item_type, item_id=item_id))
    await session.commit()
    return True


async def list_favorites(session: AsyncSession, user_id: int) -> list[Favorite]:
    return list((await session.scalars(select(Favorite).where(Favorite.user_id == user_id).order_by(Favorite.created_at.desc()))).all())


async def toggle_subscription(session: AsyncSession, user_id: int, story_id: int) -> bool:
    subscription = await session.scalar(
        select(Subscription).where(Subscription.user_id == user_id, Subscription.story_id == story_id)
    )
    if subscription:
        subscription.is_enabled = not subscription.is_enabled
        await session.commit()
        return subscription.is_enabled
    session.add(Subscription(user_id=user_id, story_id=story_id, is_enabled=True))
    await session.commit()
    return True


async def list_updates(session: AsyncSession, limit: int = 5) -> list[UpdatePost]:
    return list(
        (await session.scalars(select(UpdatePost).where(UpdatePost.is_published.is_(True)).order_by(UpdatePost.created_at.desc()).limit(limit))).all()
    )


async def save_progress(session: AsyncSession, user_id: int, story_id: int, season_id: int, episode_id: int) -> None:
    progress = await session.scalar(select(Progress).where(Progress.user_id == user_id, Progress.story_id == story_id))
    if progress is None:
        session.add(Progress(user_id=user_id, story_id=story_id, season_id=season_id, episode_id=episode_id))
    else:
        progress.season_id = season_id
        progress.episode_id = episode_id
    await session.commit()


async def global_search(session: AsyncSession, query: str) -> dict[str, list]:
    like_query = f"%{query}%"
    stories = list(
        (await session.scalars(select(Story).where(Story.is_published.is_(True), Story.title.ilike(like_query)).limit(5))).all()
    )
    characters = list((await session.scalars(select(Character).where(Character.name.ilike(like_query)).limit(5))).all())
    episodes = list(
        (
            await session.scalars(
                select(Episode).where(
                    Episode.is_published.is_(True),
                    or_(Episode.title.ilike(like_query), Episode.summary.ilike(like_query), Episode.guide_intro.ilike(like_query)),
                ).limit(5)
            )
        ).all()
    )
    choices = list(
        (
            await session.scalars(
                select(Choice).where(or_(Choice.text.ilike(like_query), Choice.consequence.ilike(like_query), Choice.tags.ilike(like_query))).limit(5)
            )
        ).all()
    )
    return {"stories": stories, "characters": characters, "episodes": episodes, "choices": choices}


async def admin_stats(session: AsyncSession) -> dict[str, int]:
    return {
        "users": await session.scalar(select(func.count(User.id))) or 0,
        "stories": await session.scalar(select(func.count(Story.id))) or 0,
        "episodes": await session.scalar(select(func.count(Episode.id))) or 0,
        "choices": await session.scalar(select(func.count(Choice.id))) or 0,
        "favorites": await session.scalar(select(func.count(Favorite.id))) or 0,
        "subscriptions": await session.scalar(select(func.count(Subscription.id)).where(Subscription.is_enabled.is_(True))) or 0,
    }


async def create_story(session: AsyncSession, title: str, description: str, genre: str | None = None) -> Story:
    slug = title.lower().replace(" ", "-")[:100]
    story = Story(title=title.strip(), slug=slug, description=description.strip(), genre=genre)
    session.add(story)
    await session.commit()
    await session.refresh(story)
    return story


async def delete_story(session: AsyncSession, story_id: int) -> None:
    await session.execute(delete(Story).where(Story.id == story_id))
    await session.commit()
