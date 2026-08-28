from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(gt=0, le=65_535)
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)

    redis_host: str = Field(min_length=1)
    redis_port: int = Field(gt=0, le=65_535)
    redis_db: int = Field(ge=0)

    club_timezone: str = Field(default="Europe/Moscow", min_length=1)

    telegram_bot_token: SecretStr = Field(min_length=1)
    owner_panel_banner_file_id: str | None = None
    admin_panel_banner_file_id: str | None = None
    trainer_panel_banner_file_id: str | None = None
    athlete_panel_banner_file_id: str | None = None
    role_selector_banner_file_id: str | None = None

    @field_validator("club_timezone")
    @classmethod
    def validate_club_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("club_timezone must be a valid IANA timezone") from error
        return value

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{database}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
