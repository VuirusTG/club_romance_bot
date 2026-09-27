from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import SocialPost, SocialPostVariant, SocialPublication, UserAttribution
from bot.services.content_engine.types import PostStatus, VariantStatus


async def create_social_post(
    session: AsyncSession,
    topic: str,
    source_text: str,
    created_by: int,
    target_story_id: int | None = None,
    status: str = PostStatus.DRAFT.value,
    scheduled_at: datetime | None = None,
) -> SocialPost:
    post = SocialPost(
        topic=topic.strip(),
        source_text=source_text.strip(),
        created_by=created_by,
        target_story_id=target_story_id,
        status=status,
        scheduled_at=scheduled_at,
    )
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return post


async def create_variant(
    session: AsyncSession,
    post_id: int,
    platform: str,
    text: str,
    image_prompt: str | None = None,
    image_url: str | None = None,
    status: str = VariantStatus.DRAFT.value,
) -> SocialPostVariant:
    variant = SocialPostVariant(
        post_id=post_id,
        platform=platform,
        text=text.strip(),
        image_prompt=image_prompt.strip() if image_prompt else None,
        image_url=image_url,
        status=status,
    )
    session.add(variant)
    await session.commit()
    await session.refresh(variant)
    return variant


async def get_post_with_variants(session: AsyncSession, post_id: int) -> SocialPost | None:
    stmt = (
        select(SocialPost)
        .options(
            selectinload(SocialPost.variants).selectinload(SocialPostVariant.publications),
            selectinload(SocialPost.target_story),
        )
        .where(SocialPost.id == post_id)
    )
    return await session.scalar(stmt)


async def get_variant(session: AsyncSession, variant_id: int) -> SocialPostVariant | None:
    stmt = (
        select(SocialPostVariant)
        .options(selectinload(SocialPostVariant.post))
        .where(SocialPostVariant.id == variant_id)
    )
    return await session.scalar(stmt)


async def list_posts_by_status(
    session: AsyncSession,
    status: str | None = None,
    page: int = 1,
    page_size: int = 8,
) -> tuple[list[SocialPost], int]:
    base_stmt = select(SocialPost)
    count_stmt = select(func.count(SocialPost.id))

    if status:
        base_stmt = base_stmt.where(SocialPost.status == status)
        count_stmt = count_stmt.where(SocialPost.status == status)

    total = await session.scalar(count_stmt) or 0
    stmt = (
        base_stmt.options(selectinload(SocialPost.variants))
        .order_by(SocialPost.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    posts = list((await session.scalars(stmt)).all())
    return posts, total


async def update_post_status(
    session: AsyncSession,
    post_id: int,
    status: str,
    scheduled_at: datetime | None = None,
) -> None:
    post = await session.get(SocialPost, post_id)
    if post:
        post.status = status
        if scheduled_at is not None:
            post.scheduled_at = scheduled_at
        if status == PostStatus.PUBLISHED.value and not post.published_at:
            post.published_at = datetime.now(timezone.utc)
        await session.commit()


async def update_variant_text(session: AsyncSession, variant_id: int, text: str) -> None:
    variant = await session.get(SocialPostVariant, variant_id)
    if variant:
        variant.text = text.strip()
        await session.commit()


async def update_variant_image(
    session: AsyncSession,
    variant_id: int,
    image_url: str | None,
    image_prompt: str | None = None,
) -> None:
    variant = await session.get(SocialPostVariant, variant_id)
    if variant:
        variant.image_url = image_url
        if image_prompt:
            variant.image_prompt = image_prompt
        await session.commit()


async def update_variant_status(
    session: AsyncSession,
    variant_id: int,
    status: str,
    external_post_id: str | None = None,
    error_message: str | None = None,
) -> None:
    variant = await session.get(SocialPostVariant, variant_id)
    if variant:
        variant.status = status
        if external_post_id:
            variant.external_post_id = external_post_id
        if error_message is not None:
            variant.error_message = error_message
        if status == VariantStatus.PUBLISHED.value:
            variant.published_at = datetime.now(timezone.utc)
        await session.commit()


async def increment_variant_retry(session: AsyncSession, variant_id: int) -> int:
    variant = await session.get(SocialPostVariant, variant_id)
    if variant:
        variant.retry_count += 1
        await session.commit()
        return variant.retry_count
    return 0


async def record_publication(
    session: AsyncSession,
    variant_id: int,
    platform: str,
    attempt_number: int,
    status: str,
    external_post_id: str | None = None,
    response_payload: str | None = None,
) -> SocialPublication:
    pub = SocialPublication(
        variant_id=variant_id,
        platform=platform,
        attempt_number=attempt_number,
        status=status,
        external_post_id=external_post_id,
        response_payload=response_payload,
    )
    session.add(pub)
    await session.commit()
    await session.refresh(pub)
    return pub


async def record_user_attribution(
    session: AsyncSession,
    user_id: int,
    platform: str,
    post_id: int | None = None,
    campaign: str | None = None,
    raw_payload: str = "",
) -> UserAttribution:
    attribution = UserAttribution(
        user_id=user_id,
        platform=platform,
        post_id=post_id,
        campaign=campaign,
        raw_payload=raw_payload,
    )
    session.add(attribution)
    await session.commit()
    await session.refresh(attribution)
    return attribution


async def claim_due_scheduled_posts(session: AsyncSession) -> list[SocialPost]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(SocialPost)
        .options(
            selectinload(SocialPost.variants).selectinload(SocialPostVariant.publications),
            selectinload(SocialPost.target_story),
        )
        .where(
            SocialPost.status == PostStatus.SCHEDULED.value,
            SocialPost.scheduled_at <= now,
        )
    )
    # If postgresql, use with_for_update(skip_locked=True)
    bind = session.get_bind()
    if bind and "postgresql" in str(bind.dialect.name).lower():
        stmt = stmt.with_for_update(skip_locked=True)

    posts = list((await session.scalars(stmt)).all())
    for post in posts:
        post.status = PostStatus.PUBLISHING.value
    if posts:
        await session.commit()
    return posts


async def get_social_overview(session: AsyncSession) -> dict[str, int]:
    drafts = await session.scalar(
        select(func.count(SocialPost.id)).where(SocialPost.status == PostStatus.DRAFT.value)
    ) or 0
    scheduled = await session.scalar(
        select(func.count(SocialPost.id)).where(SocialPost.status == PostStatus.SCHEDULED.value)
    ) or 0
    published = await session.scalar(
        select(func.count(SocialPost.id)).where(SocialPost.status.in_([PostStatus.PUBLISHED.value, PostStatus.PARTIALLY_PUBLISHED.value]))
    ) or 0
    failed = await session.scalar(
        select(func.count(SocialPost.id)).where(SocialPost.status == PostStatus.FAILED.value)
    ) or 0
    attributions = await session.scalar(select(func.count(UserAttribution.id))) or 0
    return {
        "drafts": drafts,
        "scheduled": scheduled,
        "published": published,
        "failed": failed,
        "attributions": attributions,
    }


async def delete_social_post(session: AsyncSession, post_id: int) -> bool:
    post = await session.get(SocialPost, post_id)
    if post:
        await session.delete(post)
        await session.commit()
        return True
    return False
