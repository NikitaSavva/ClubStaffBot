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
    "ATHLETE_QR_SIGNING_SECRET",
    "ATHLETE_QR_TTL_SECONDS",
    "OWNER_PANEL_BANNER_FILE_ID",
    "ADMIN_PANEL_BANNER_FILE_ID",
    "TRAINER_PANEL_BANNER_FILE_ID",
    "ATHLETE_PANEL_BANNER_FILE_ID",
    "ROLE_SELECTOR_BANNER_FILE_ID",
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
    monkeypatch.setenv("CLUB_TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("ATHLETE_QR_SIGNING_SECRET", "s" * 32)
    monkeypatch.setenv("ATHLETE_QR_TTL_SECONDS", "600")
    monkeypatch.setenv("OWNER_PANEL_BANNER_FILE_ID", "owner-file-id")
    monkeypatch.setenv("ADMIN_PANEL_BANNER_FILE_ID", "admin-file-id")
    monkeypatch.setenv("TRAINER_PANEL_BANNER_FILE_ID", "trainer-file-id")
    monkeypatch.setenv("ATHLETE_PANEL_BANNER_FILE_ID", "athlete-file-id")
    monkeypatch.setenv("ROLE_SELECTOR_BANNER_FILE_ID", "selector-file-id")

    settings = Settings(_env_file=None)

    assert settings.database_url == (
        "postgresql+asyncpg://user:pass%3Fword@database:5432/staff_bot"
    )
    assert settings.redis_url == "redis://cache:6379/1"
    assert settings.club_timezone == "Europe/Moscow"
    assert settings.telegram_bot_token.get_secret_value() == "123456789:test-token"
    assert settings.athlete_qr_signing_secret.get_secret_value() == "s" * 32
    assert settings.athlete_qr_ttl_seconds == 600
    assert settings.owner_panel_banner_file_id == "owner-file-id"
    assert settings.admin_panel_banner_file_id == "admin-file-id"
    assert settings.trainer_panel_banner_file_id == "trainer-file-id"
    assert settings.athlete_panel_banner_file_id == "athlete-file-id"
    assert settings.role_selector_banner_file_id == "selector-file-id"


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
                f"ATHLETE_QR_SIGNING_SECRET={'s' * 32}",
                "ADMIN_PANEL_BANNER_FILE_ID=admin-file-id",
                "TRAINER_PANEL_BANNER_FILE_ID=trainer-file-id",
                "ATHLETE_PANEL_BANNER_FILE_ID=athlete-file-id",
                "ROLE_SELECTOR_BANNER_FILE_ID=selector-file-id",
            ),
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.postgres_host == "database"
    assert settings.redis_host == "cache"
    assert settings.owner_panel_banner_file_id is None
    assert settings.admin_panel_banner_file_id == "admin-file-id"
    assert settings.athlete_qr_ttl_seconds == 300


def test_settings_requires_infrastructure_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in REQUIRED_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_unknown_club_timezone() -> None:
    with pytest.raises(ValidationError):
        Settings(
            postgres_host="database",
            postgres_port=5432,
            postgres_db="staff_bot",
            postgres_user="user",
            postgres_password="password",
            redis_host="cache",
            redis_port=6379,
            redis_db=0,
            club_timezone="Sochi/Unknown",
            telegram_bot_token="123456789:test-token",
            athlete_qr_signing_secret="s" * 32,
            _env_file=None,
        )


@pytest.mark.parametrize("ttl_seconds", [0, -1])
def test_settings_rejects_non_positive_athlete_qr_ttl(
    ttl_seconds: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            postgres_host="database",
            postgres_port=5432,
            postgres_db="staff_bot",
            postgres_user="user",
            postgres_password="password",
            redis_host="cache",
            redis_port=6379,
            redis_db=0,
            telegram_bot_token="123456789:test-token",
            athlete_qr_signing_secret="s" * 32,
            athlete_qr_ttl_seconds=ttl_seconds,
            _env_file=None,
        )
