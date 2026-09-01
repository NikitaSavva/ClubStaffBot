import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from application.scanner import (
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
)
from infrastructure.telegram_webapp import (
    AiogramTelegramWebAppInitDataVerifier,
)

BOT_TOKEN = "123456789:test-bot-token"
OTHER_BOT_TOKEN = "987654321:other-bot-token"
TELEGRAM_USER_ID = 42_001
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
MAX_AGE_SECONDS = 3600


class FrozenClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


def signed_init_data(
    *,
    bot_token: str = BOT_TOKEN,
    auth_date: int | str = int(NOW.timestamp()),
    user: str | None = None,
    include_hash: bool = True,
) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
    }
    if user is None:
        fields["user"] = json.dumps(
            {
                "id": TELEGRAM_USER_ID,
                "first_name": "Администратор",
                "is_bot": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    elif user:
        fields["user"] = user

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    if include_hash:
        fields["hash"] = signature
    return urlencode(fields)


def verifier(
    *,
    bot_token: str = BOT_TOKEN,
    clock: FrozenClock | None = None,
) -> AiogramTelegramWebAppInitDataVerifier:
    return AiogramTelegramWebAppInitDataVerifier(
        bot_token=bot_token,
        max_age_seconds=MAX_AGE_SECONDS,
        clock=clock or FrozenClock(),
    )


def test_valid_signed_init_data_returns_typed_trusted_user() -> None:
    trusted = verifier().verify(signed_init_data())

    assert trusted.telegram_user_id == TELEGRAM_USER_ID


def test_auth_date_is_valid_at_exact_max_age_boundary() -> None:
    raw = signed_init_data(
        auth_date=int((NOW - timedelta(seconds=MAX_AGE_SECONDS)).timestamp())
    )

    assert verifier().verify(raw).telegram_user_id == TELEGRAM_USER_ID


def test_expired_auth_date_is_controlled_without_sleep() -> None:
    raw = signed_init_data(
        auth_date=int(
            (NOW - timedelta(seconds=MAX_AGE_SECONDS + 1)).timestamp()
        )
    )

    with pytest.raises(TelegramWebAppInitDataExpiredError):
        verifier().verify(raw)


def test_future_auth_date_is_rejected() -> None:
    raw = signed_init_data(
        auth_date=int((NOW + timedelta(seconds=1)).timestamp())
    )

    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(raw)


def test_tampered_init_data_is_rejected() -> None:
    raw = signed_init_data().replace(
        str(TELEGRAM_USER_ID),
        str(TELEGRAM_USER_ID + 1),
    )

    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(raw)


def test_wrong_bot_token_is_rejected() -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier(bot_token=OTHER_BOT_TOKEN).verify(signed_init_data())


def test_missing_hash_is_rejected() -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(signed_init_data(include_hash=False))


def test_signed_init_data_without_user_is_rejected() -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(signed_init_data(user=""))


@pytest.mark.parametrize(
    "user_payload",
    ["not-json", '{"id":"not-an-integer","first_name":"A"}'],
)
def test_invalid_user_payload_is_controlled(user_payload: str) -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(signed_init_data(user=user_payload))


def test_invalid_auth_date_is_controlled() -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify(signed_init_data(auth_date="not-a-timestamp"))


def test_empty_raw_init_data_is_controlled() -> None:
    with pytest.raises(TelegramWebAppInitDataInvalidError):
        verifier().verify("")
