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

from application.trainer_notifications import (
    PermanentTrainerNotifierError,
    RetryableTrainerNotifierError,
    TrainerNotificationMessage,
)
from presentation.telegram.trainer_notifications import (
    AiogramTrainerNotifier,
    format_trainer_notification,
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


def message(*, expected: int = 12, confirmed: int = 7) -> TrainerNotificationMessage:
    return TrainerNotificationMessage(
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые #1",
        starts_at=datetime(2026, 9, 2, 19, 0, tzinfo=CLUB_TIMEZONE),
        ends_at=datetime(2026, 9, 2, 20, 30, tzinfo=CLUB_TIMEZONE),
        expected_count=expected,
        confirmed_count=confirmed,
    )


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=42, user_id=42),
    )


def test_formats_materialized_start_end_counts_and_people_word() -> None:
    assert format_trainer_notification(message()) == (
        "Через 5 минут тренировка\n\n"
        "Кикбоксинг · Взрослые #1 · 19:00–20:30\n\n"
        "Ожидалось: 12 человек\n"
        "Отметились: 7 человек"
    )
    assert "2 человека" in format_trainer_notification(
        message(expected=2)
    )
    assert "0 человек" in format_trainer_notification(
        message(confirmed=0)
    )


@pytest.mark.parametrize(
    ("count", "word"),
    [
        (1, "человек"),
        (2, "человека"),
        (5, "человек"),
        (11, "человек"),
        (21, "человек"),
        (22, "человека"),
        (25, "человек"),
    ],
)
def test_people_word_boundaries(count: int, word: str) -> None:
    assert f"Ожидалось: {count} {word}" in format_trainer_notification(
        message(expected=count)
    )


async def test_proactive_sender_does_not_change_active_ui_message() -> None:
    state = make_state()
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
    notifier = AiogramTrainerNotifier(cast(Bot, bot))

    await notifier.send(telegram_id=42, message=message(expected=0, confirmed=0))

    assert await get_active_ui_message(state) == active
    assert bot.calls == [
        {
            "chat_id": 42,
            "text": (
                "Через 5 минут тренировка\n\n"
                "Кикбоксинг · Взрослые #1 · 19:00–20:30\n\n"
                "Ожидалось: 0 человек\n"
                "Отметились: 0 человек"
            ),
            "request_timeout": 20,
        }
    ]


async def test_retry_after_is_translated_with_server_delay() -> None:
    bot = FakeBot()
    bot.error = TelegramRetryAfter(
        method=SendMessage(chat_id=42, text="test"),
        message="retry later",
        retry_after=90,
    )
    notifier = AiogramTrainerNotifier(cast(Bot, bot))

    with pytest.raises(RetryableTrainerNotifierError) as raised:
        await notifier.send(telegram_id=42, message=message())

    assert raised.value.retry_after_seconds == 90


async def test_network_error_is_retryable() -> None:
    bot = FakeBot()
    bot.error = TelegramNetworkError(
        method=SendMessage(chat_id=42, text="test"),
        message="network unavailable",
    )
    notifier = AiogramTrainerNotifier(cast(Bot, bot))

    with pytest.raises(RetryableTrainerNotifierError) as raised:
        await notifier.send(telegram_id=42, message=message())

    assert raised.value.retry_after_seconds is None


async def test_forbidden_error_is_terminal() -> None:
    bot = FakeBot()
    bot.error = TelegramForbiddenError(
        method=SendMessage(chat_id=42, text="test"),
        message="bot was blocked",
    )
    notifier = AiogramTrainerNotifier(cast(Bot, bot))

    with pytest.raises(PermanentTrainerNotifierError):
        await notifier.send(telegram_id=42, message=message())
