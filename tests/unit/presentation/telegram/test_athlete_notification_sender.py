from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from application.athlete_notifications import AthleteNotificationMessage
from application.notification_delivery import (
    PermanentNotificationSenderError,
    RetryableNotificationSenderError,
)
from presentation.telegram.athlete_notifications import (
    AiogramAthleteNotifier,
    format_athlete_notification,
)
from presentation.telegram.ui_context import (
    ActiveUiMessage,
    UiMessageKind,
    get_active_ui_message,
    set_active_ui_message,
)

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def send_message(self, **kwargs: Any) -> object:
        if self.error is not None:
            raise self.error
        self.calls.append(kwargs)
        return object()


def message() -> AthleteNotificationMessage:
    return AthleteNotificationMessage(
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые #1",
        starts_at=datetime(2026, 9, 2, 19, 0, tzinfo=CLUB_TIMEZONE),
        ends_at=datetime(2026, 9, 2, 20, 30, tzinfo=CLUB_TIMEZONE),
    )


def test_formats_only_approved_materialized_session_fields() -> None:
    assert format_athlete_notification(message()) == (
        "Через 2 часа тренировка\n\n"
        "Кикбоксинг · Взрослые #1 · 19:00–20:30"
    )


async def test_proactive_sender_does_not_change_active_ui_message() -> None:
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=42, user_id=42),
    )
    active = ActiveUiMessage(
        chat_id=42,
        message_id=99,
        kind=UiMessageKind.TEXT,
        media_key=None,
        content_fingerprint="menu-content",
        keyboard_fingerprint="menu-keyboard",
    )
    await set_active_ui_message(state, active)
    bot = FakeBot()

    await AiogramAthleteNotifier(cast(Bot, bot)).send(
        telegram_id=42,
        message=message(),
    )

    assert await get_active_ui_message(state) == active
    assert bot.calls == [
        {
            "chat_id": 42,
            "text": (
                "Через 2 часа тренировка\n\n"
                "Кикбоксинг · Взрослые #1 · 19:00–20:30"
            ),
            "request_timeout": 20,
        }
    ]


async def test_retry_after_preserves_server_delay() -> None:
    bot = FakeBot()
    bot.error = TelegramRetryAfter(
        method=SendMessage(chat_id=42, text="test"),
        message="retry later",
        retry_after=90,
    )

    with pytest.raises(RetryableNotificationSenderError) as raised:
        await AiogramAthleteNotifier(cast(Bot, bot)).send(
            telegram_id=42,
            message=message(),
        )

    assert raised.value.retry_after_seconds == 90


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (
            TelegramNetworkError(
                method=SendMessage(chat_id=42, text="test"),
                message="network unavailable",
            ),
            RetryableNotificationSenderError,
        ),
        (
            TelegramForbiddenError(
                method=SendMessage(chat_id=42, text="test"),
                message="blocked",
            ),
            PermanentNotificationSenderError,
        ),
    ],
)
async def test_telegram_error_classification(
    error: Exception,
    expected_error: type[Exception],
) -> None:
    bot = FakeBot()
    bot.error = error

    with pytest.raises(expected_error):
        await AiogramAthleteNotifier(cast(Bot, bot)).send(
            telegram_id=42,
            message=message(),
        )
