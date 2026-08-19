from pathlib import Path

import pytest
from pydantic import ValidationError

from bootstrap.config import Settings

REQUIRED_VARIABLES = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_ID",
)


def test_settings_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "database")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "staff_bot")
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pass?word")
    monkeypatch.setenv("REDIS_HOST", "cache")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_DB", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "987654321")

    settings = Settings(_env_file=None)

    assert settings.database_url == (
        "postgresql+asyncpg://user:pass%3Fword@database:5432/staff_bot"
    )
    assert settings.redis_url == "redis://cache:6379/1"
    assert settings.telegram_bot_token.get_secret_value() == "123456789:test-token"
    assert settings.telegram_owner_id == 987654321


def test_settings_loads_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for variable in REQUIRED_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "POSTGRES_HOST=database",
                "POSTGRES_PORT=5432",
                "POSTGRES_DB=staff_bot",
                "POSTGRES_USER=user",
                "POSTGRES_PASSWORD=password",
                "REDIS_HOST=cache",
                "REDIS_PORT=6379",
                "REDIS_DB=0",
                "TELEGRAM_BOT_TOKEN=123456789:test-token",
                "TELEGRAM_OWNER_ID=987654321",
            ),
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.postgres_host == "database"
    assert settings.redis_host == "cache"


def test_settings_requires_infrastructure_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in REQUIRED_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
