from dataclasses import dataclass, field
from enum import Enum


class SocialPlatform(str, Enum):
    TELEGRAM = "telegram"
    VK = "vk"
    INSTAGRAM = "instagram"
    THREADS = "threads"


class PostStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    PARTIALLY_PUBLISHED = "PARTIALLY_PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VariantStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PublicationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DRY_RUN = "DRY_RUN"


@dataclass
class GeneratedVariant:
    platform: SocialPlatform
    text: str
    image_prompt: str = ""


@dataclass
class AIGenerationResult:
    variants: dict[SocialPlatform, GeneratedVariant] = field(default_factory=dict)
    image_prompt: str = ""


@dataclass
class PublishResult:
    success: bool
    external_post_id: str | None = None
    error_message: str | None = None
    is_dry_run: bool = False
    raw_response: str | None = None
