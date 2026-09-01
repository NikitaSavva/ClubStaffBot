from fastapi.testclient import TestClient

from bootstrap.config import Settings
from entrypoints.api import create_app


def test_health_endpoint() -> None:
    settings = Settings(
        postgres_host="database",
        postgres_port=5432,
        postgres_db="staff_bot",
        postgres_user="user",
        postgres_password="password",
        redis_host="cache",
        redis_port=6379,
        redis_db=0,
        telegram_bot_token="123456789:test-token",
        telegram_webapp_base_url="https://scanner.example.test",
        athlete_qr_signing_secret="s" * 32,
        _env_file=None,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
