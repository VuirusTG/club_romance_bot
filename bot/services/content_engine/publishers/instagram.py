import asyncio
import logging
import aiohttp

from bot.config import get_settings
from bot.database.models import SocialPostVariant
from bot.services.content_engine.publishers.base import BaseSocialPublisher
from bot.services.content_engine.types import PublishResult, SocialPlatform

logger = logging.getLogger(__name__)


class InstagramPublisher(BaseSocialPublisher):
    META_GRAPH_VERSION = "v19.0"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def platform_name(self) -> str:
        return SocialPlatform.INSTAGRAM.value

    def is_configured(self) -> bool:
        return bool(self.settings.meta_access_token and self.settings.instagram_business_account_id)

    async def publish(self, variant: SocialPostVariant, dry_run: bool = False) -> PublishResult:
        if dry_run or self.settings.social_publish_dry_run:
            logger.info(f"[DRY-RUN] Publishing to Instagram ({self.settings.instagram_business_account_id}): {variant.text[:60]}...")
            return PublishResult(
                success=True,
                external_post_id=f"dry_run_ig_{variant.id}",
                is_dry_run=True,
            )

        if not self.is_configured():
            return PublishResult(
                success=False,
                error_message="⚠️ Instagram не подключён (отсутствуют META_ACCESS_TOKEN или INSTAGRAM_BUSINESS_ACCOUNT_ID)",
            )

        if not variant.image_url:
            return PublishResult(
                success=False,
                error_message="Instagram API требует наличие публичного URL изображения (image_url) для публикации.",
            )

        ig_account_id = self.settings.instagram_business_account_id
        access_token = self.settings.meta_access_token
        base_url = f"https://graph.facebook.com/{self.META_GRAPH_VERSION}/{ig_account_id}"

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Create media container
                create_url = f"{base_url}/media"
                params = {
                    "image_url": variant.image_url,
                    "caption": variant.text,
                    "access_token": access_token,
                }
                async with session.post(create_url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    data = await resp.json()
                    if "error" in data:
                        err_msg = data["error"].get("message", "Meta Graph API error")
                        return PublishResult(
                            success=False,
                            error_message=f"Instagram Container error: {err_msg}",
                            raw_response=str(data),
                        )
                    creation_id = data.get("id")

                # Allow a short moment for media container processing
                await asyncio.sleep(2)

                # Step 2: Publish media container
                publish_url = f"{base_url}/media_publish"
                pub_params = {
                    "creation_id": creation_id,
                    "access_token": access_token,
                }
                async with session.post(publish_url, data=pub_params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    pub_data = await resp.json()
                    if "error" in pub_data:
                        err_msg = pub_data["error"].get("message", "Meta Graph API Publish error")
                        return PublishResult(
                            success=False,
                            error_message=f"Instagram Publish error: {err_msg}",
                            raw_response=str(pub_data),
                        )
                    media_id = pub_data.get("id")
                    return PublishResult(
                        success=True,
                        external_post_id=str(media_id),
                        is_dry_run=False,
                        raw_response=str(pub_data),
                    )

        except Exception as e:
            logger.error(f"Instagram publishing exception: {e}", exc_info=True)
            return PublishResult(
                success=False,
                error_message=f"Instagram Network/API error: {str(e)}",
            )
