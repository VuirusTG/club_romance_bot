from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///./club_romance.db"
    log_level: str = "INFO"
    port: int = 7860
    enable_web: bool = True

    # Social Media Content Engine
    telegram_channel_id: str | None = None
    vk_group_id: str | None = None
    vk_access_token: str | None = None
    meta_access_token: str | None = None
    instagram_business_account_id: str | None = None
    threads_user_id: str | None = None
    threads_access_token: str | None = None
    openai_api_key: str | None = None
    social_publish_dry_run: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        values: set[int] = set()
        for raw_id in self.admin_ids.split(","):
            raw_id = raw_id.strip()
            if raw_id:
                values.add(int(raw_id))
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
