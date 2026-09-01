from fastapi.testclient import TestClient

from bootstrap.config import Settings
from entrypoints.api import create_app


def settings() -> Settings:
    return Settings(
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


def test_scanner_webapp_and_static_assets_are_served() -> None:
    with TestClient(create_app(settings())) as client:
        html = client.get("/webapp/scanner")
        head = client.head("/webapp/scanner")
        javascript = client.get("/webapp/static/scanner.js")
        stylesheet = client.get("/webapp/static/scanner.css")

    assert html.status_code == 200
    assert head.status_code == 200
    assert javascript.status_code == 200
    assert stylesheet.status_code == 200
    assert "https://telegram.org/js/telegram-web-app.js" in html.text
    assert "showScanQrPopup" in javascript.text
    assert "closeScanQrPopup" in javascript.text
    assert "textContent" in javascript.text
    assert "innerHTML" not in javascript.text
    assert "getUserMedia" not in javascript.text
    assert "navigator.mediaDevices" not in javascript.text
    assert "jsQR" not in javascript.text
    assert "127.0.0.1" in javascript.text
    assert "isLocalPreview" in javascript.text


def test_webapp_assets_do_not_expose_secrets_or_identity() -> None:
    secret_values = (
        "123456789:test-token",
        "s" * 32,
        "telegram_id",
        "athlete_public_id",
    )
    with TestClient(create_app(settings())) as client:
        content = "\n".join(
            (
                client.get("/webapp/scanner").text,
                client.get("/webapp/static/scanner.js").text,
                client.get("/webapp/static/scanner.css").text,
            )
        )

    assert all(secret not in content for secret in secret_values)
