import asyncio
import logging
import aiohttp

from bot.config import get_settings
from bot.database.models import SocialPostVariant
from bot.services.content_engine.publishers.base import BaseSocialPublisher
from bot.services.content_engine.types import PublishResult, SocialPlatform

logger = logging.getLogger(__name__)


class ThreadsPublisher(BaseSocialPublisher):
    THREADS_API_VERSION = "v1.0"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def platform_name(self) -> str:
        return SocialPlatform.THREADS.value

    def is_configured(self) -> bool:
        return bool(self.settings.threads_access_token and self.settings.threads_user_id)

    async def publish(self, variant: SocialPostVariant, dry_run: bool = False) -> PublishResult:
        if dry_run or self.settings.social_publish_dry_run:
            logger.info(f"[DRY-RUN] Publishing to Threads ({self.settings.threads_user_id}): {variant.text[:60]}...")
            return PublishResult(
                success=True,
                external_post_id=f"dry_run_threads_{variant.id}",
                is_dry_run=True,
            )

        if not self.is_configured():
            return PublishResult(
                success=False,
                error_message="⚠️ Threads не подключён (отсутствуют THREADS_ACCESS_TOKEN или THREADS_USER_ID)",
            )

        threads_user_id = self.settings.threads_user_id
        access_token = self.settings.threads_access_token
        base_url = f"https://graph.threads.net/{self.THREADS_API_VERSION}/{threads_user_id}"

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Create Threads media container
                create_url = f"{base_url}/threads"
                params = {
                    "text": variant.text,
                    "access_token": access_token,
                }
                if variant.image_url:
                    params["media_type"] = "IMAGE"
                    params["image_url"] = variant.image_url
                else:
                    params["media_type"] = "TEXT"

                async with session.post(create_url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    data = await resp.json()
                    if "error" in data:
                        err_msg = data["error"].get("message", "Threads API Container error")
                        return PublishResult(
                            success=False,
                            error_message=f"Threads Container error: {err_msg}",
                            raw_response=str(data),
                        )
                    creation_id = data.get("id")

                await asyncio.sleep(2)

                # Step 2: Publish Threads container
                publish_url = f"{base_url}/threads_publish"
                pub_params = {
                    "creation_id": creation_id,
                    "access_token": access_token,
                }
                async with session.post(publish_url, data=pub_params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    pub_data = await resp.json()
                    if "error" in pub_data:
                        err_msg = pub_data["error"].get("message", "Threads API Publish error")
                        return PublishResult(
                            success=False,
                            error_message=f"Threads Publish error: {err_msg}",
                            raw_response=str(pub_data),
                        )
                    threads_post_id = pub_data.get("id")
                    return PublishResult(
                        success=True,
                        external_post_id=str(threads_post_id),
                        is_dry_run=False,
                        raw_response=str(pub_data),
                    )

        except Exception as e:
            logger.error(f"Threads publishing exception: {e}", exc_info=True)
            return PublishResult(
                success=False,
                error_message=f"Threads Network/API error: {str(e)}",
            )
