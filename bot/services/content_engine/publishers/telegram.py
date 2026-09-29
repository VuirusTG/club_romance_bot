import logging
from aiogram import Bot
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.database.models import SocialPostVariant
from bot.services.content_engine.publishers.base import BaseSocialPublisher
from bot.services.content_engine.types import PublishResult, SocialPlatform

logger = logging.getLogger(__name__)


class TelegramPublisher(BaseSocialPublisher):
    def __init__(self, bot: Bot | None = None) -> None:
        self.settings = get_settings()
        self.bot = bot

    @property
    def platform_name(self) -> str:
        return SocialPlatform.TELEGRAM.value

    def is_configured(self) -> bool:
        return bool(self.settings.telegram_channel_id)

    async def publish(self, variant: SocialPostVariant, dry_run: bool = False) -> PublishResult:
        if dry_run or self.settings.social_publish_dry_run:
            logger.info(f"[DRY-RUN] Publishing to Telegram Channel ({self.settings.telegram_channel_id}): {variant.text[:60]}...")
            return PublishResult(
                success=True,
                external_post_id=f"dry_run_tg_{variant.id}",
                is_dry_run=True,
            )

        if not self.is_configured():
            return PublishResult(
                success=False,
                error_message="⚠️ Telegram-канал не настроен (TELEGRAM_CHANNEL_ID не задан)",
            )

        if not self.bot:
            return PublishResult(
                success=False,
                error_message="Бот-клиент недоступен для отправки сообщения.",
            )

        try:
            channel_id = self.settings.telegram_channel_id
            if channel_id and (channel_id.startswith("-") or channel_id.isdigit()):
                try:
                    channel_id = int(channel_id)
                except ValueError:
                    pass
            if variant.image_url:
                msg = await self.bot.send_photo(
                    chat_id=channel_id,
                    photo=variant.image_url,
                    caption=variant.text,
                    parse_mode=ParseMode.HTML,
                )
            else:
                msg = await self.bot.send_message(
                    chat_id=channel_id,
                    text=variant.text,
                    parse_mode=ParseMode.HTML,
                )
            return PublishResult(
                success=True,
                external_post_id=str(msg.message_id),
                is_dry_run=False,
            )
        except Exception as e:
            logger.error(f"Failed to publish to Telegram channel: {e}", exc_info=True)
            return PublishResult(
                success=False,
                error_message=f"Telegram API error: {str(e)}",
            )
