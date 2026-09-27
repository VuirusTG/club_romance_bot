import logging
import aiohttp

from bot.config import get_settings
from bot.database.models import SocialPostVariant
from bot.services.content_engine.publishers.base import BaseSocialPublisher
from bot.services.content_engine.types import PublishResult, SocialPlatform

logger = logging.getLogger(__name__)


class VkPublisher(BaseSocialPublisher):
    VK_API_VERSION = "5.199"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def platform_name(self) -> str:
        return SocialPlatform.VK.value

    def is_configured(self) -> bool:
        return bool(self.settings.vk_access_token and self.settings.vk_group_id)

    async def publish(self, variant: SocialPostVariant, dry_run: bool = False) -> PublishResult:
        if dry_run or self.settings.social_publish_dry_run:
            logger.info(f"[DRY-RUN] Publishing to VK Group ({self.settings.vk_group_id}): {variant.text[:60]}...")
            return PublishResult(
                success=True,
                external_post_id=f"dry_run_vk_{variant.id}",
                is_dry_run=True,
            )

        if not self.is_configured():
            return PublishResult(
                success=False,
                error_message="⚠️ VK не подключён (отсутствуют VK_ACCESS_TOKEN или VK_GROUP_ID)",
            )

        try:
            group_id = int(self.settings.vk_group_id.lstrip("-"))
            owner_id = -group_id

            params = {
                "access_token": self.settings.vk_access_token,
                "v": self.VK_API_VERSION,
                "owner_id": owner_id,
                "from_group": 1,
                "message": variant.text,
            }

            url = "https://api.vk.com/method/wall.post"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    data = await resp.json()
                    if "error" in data:
                        err_msg = data["error"].get("error_msg", "Unknown VK error")
                        err_code = data["error"].get("error_code")
                        return PublishResult(
                            success=False,
                            error_message=f"VK API error {err_code}: {err_msg}",
                            raw_response=str(data),
                        )
                    post_id = data.get("response", {}).get("post_id")
                    return PublishResult(
                        success=True,
                        external_post_id=f"{owner_id}_{post_id}",
                        is_dry_run=False,
                        raw_response=str(data),
                    )
        except Exception as e:
            logger.error(f"VK publishing exception: {e}", exc_info=True)
            return PublishResult(
                success=False,
                error_message=f"VK Network/System error: {str(e)}",
            )
