import asyncio
import logging
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.database.models import SocialPost, SocialPostVariant
from bot.database.repositories import social
from bot.services.content_engine.publishers import (
    BaseSocialPublisher,
    InstagramPublisher,
    TelegramPublisher,
    ThreadsPublisher,
    VkPublisher,
)
from bot.services.content_engine.types import (
    PostStatus,
    PublicationStatus,
    PublishResult,
    SocialPlatform,
    VariantStatus,
)

logger = logging.getLogger(__name__)


def get_platform_publishers(bot: Bot | None = None) -> dict[str, BaseSocialPublisher]:
    return {
        SocialPlatform.TELEGRAM.value: TelegramPublisher(bot=bot),
        SocialPlatform.VK.value: VkPublisher(),
        SocialPlatform.INSTAGRAM.value: InstagramPublisher(),
        SocialPlatform.THREADS.value: ThreadsPublisher(),
    }


async def publish_single_variant(
    session: AsyncSession,
    variant: SocialPostVariant,
    publisher: BaseSocialPublisher,
    dry_run: bool = False,
) -> PublishResult:
    # Protection against double posting (Idempotency)
    if variant.status == VariantStatus.PUBLISHED.value or variant.external_post_id:
        logger.info(f"Variant {variant.id} ({variant.platform}) is already published. Skipping duplicate.")
        return PublishResult(
            success=True,
            external_post_id=variant.external_post_id,
            is_dry_run=dry_run,
        )

    await social.update_variant_status(session, variant.id, VariantStatus.PUBLISHING.value)
    result = await publisher.publish(variant, dry_run=dry_run)

    attempt_number = variant.retry_count + 1
    pub_status = (
        PublicationStatus.DRY_RUN.value
        if result.is_dry_run
        else (PublicationStatus.SUCCESS.value if result.success else PublicationStatus.ERROR.value)
    )

    await social.record_publication(
        session=session,
        variant_id=variant.id,
        platform=variant.platform,
        attempt_number=attempt_number,
        status=pub_status,
        external_post_id=result.external_post_id,
        response_payload=result.raw_response or result.error_message,
    )

    if result.success:
        await social.update_variant_status(
            session=session,
            variant_id=variant.id,
            status=VariantStatus.PUBLISHED.value,
            external_post_id=result.external_post_id,
            error_message=None,
        )
    else:
        retries = await social.increment_variant_retry(session, variant.id)
        final_status = VariantStatus.FAILED.value if retries >= 3 else VariantStatus.APPROVED.value
        await social.update_variant_status(
            session=session,
            variant_id=variant.id,
            status=final_status,
            error_message=result.error_message,
        )

    return result


async def dispatch_post(
    session: AsyncSession,
    post: SocialPost,
    publishers: dict[str, BaseSocialPublisher],
    target_platform: str | None = None,
    dry_run: bool = False,
) -> dict[str, PublishResult]:
    results: dict[str, PublishResult] = {}

    variants_to_publish = [
        v for v in post.variants
        if target_platform is None or v.platform == target_platform
    ]

    for variant in variants_to_publish:
        pub = publishers.get(variant.platform)
        if not pub:
            logger.warning(f"No publisher found for platform: {variant.platform}")
            continue

        res = await publish_single_variant(session, variant, pub, dry_run=dry_run)
        results[variant.platform] = res

    # Refresh post variants state to compute master post status
    refreshed_post = await social.get_post_with_variants(session, post.id)
    if refreshed_post and refreshed_post.variants:
        all_published = all(v.status == VariantStatus.PUBLISHED.value for v in refreshed_post.variants)
        any_published = any(v.status == VariantStatus.PUBLISHED.value for v in refreshed_post.variants)
        all_failed = all(v.status == VariantStatus.FAILED.value for v in refreshed_post.variants)

        if all_published:
            new_status = PostStatus.PUBLISHED.value
        elif any_published:
            new_status = PostStatus.PARTIALLY_PUBLISHED.value
        elif all_failed:
            new_status = PostStatus.FAILED.value
        else:
            new_status = PostStatus.SCHEDULED.value

        await social.update_post_status(session, post.id, new_status)

    return results


async def run_scheduled_publications_once(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot | None = None,
    dry_run: bool | None = None,
) -> int:
    settings = get_settings()
    is_dry_run = settings.social_publish_dry_run if dry_run is None else dry_run
    publishers = get_platform_publishers(bot)

    async with session_factory() as session:
        due_posts = await social.claim_due_scheduled_posts(session)

    if not due_posts:
        return 0

    logger.info(f"Processing {len(due_posts)} due scheduled posts (dry_run={is_dry_run})...")
    for post in due_posts:
        try:
            async with session_factory() as session:
                full_post = await social.get_post_with_variants(session, post.id)
                if full_post:
                    await dispatch_post(session, full_post, publishers, dry_run=is_dry_run)
        except Exception as e:
            logger.error(f"Error publishing scheduled post #{post.id}: {e}", exc_info=True)
            async with session_factory() as session:
                await social.update_post_status(session, post.id, PostStatus.FAILED.value)

    return len(due_posts)


class SafeContentScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot | None = None,
        poll_interval_seconds: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.bot = bot
        self.poll_interval = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> asyncio.Task:
        if self._task and not self._task.done():
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Safe Content Scheduler started (interval: {self.poll_interval}s).")
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Safe Content Scheduler stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await run_scheduled_publications_once(self.session_factory, self.bot)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)
