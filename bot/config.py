from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///./club_romance.db"
    log_level: str = "INFO"
    port: int = 7860
    enable_web: bool = True

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
