from abc import ABC, abstractmethod

from bot.database.models import SocialPostVariant
from bot.services.content_engine.types import PublishResult


class BaseSocialPublisher(ABC):
    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    async def publish(self, variant: SocialPostVariant, dry_run: bool = False) -> PublishResult:
        pass
