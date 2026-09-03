from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from aiogram.types import InlineKeyboardMarkup

from application.subscriptions import (
    GetLatestAthleteSubscriptionResult,
    LatestSubscriptionDetails,
    MySubscriptionGroup,
)
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from presentation.telegram.handlers.subscription_correction import (
    SubscriptionCorrectionAction,
    SubscriptionCorrectionCallback,
    _card_keyboard,
    _draft_keyboard,
    parse_corrected_expires_at,
)
from presentation.telegram.presenters.subscriptions import (
    NO_SUBSCRIPTION_TEXT,
    format_latest_subscription_card,
)

MOSCOW = ZoneInfo("Europe/Moscow")


def callback_texts(keyboard: InlineKeyboardMarkup) -> dict[str, str]:
    inline_keyboard = keyboard.inline_keyboard
    return {
        button.callback_data: button.text
        for row in inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_corrected_expiration_replaces_only_local_calendar_date() -> None:
    original = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

    result = parse_corrected_expires_at(
        " 18.09.2026 ",
        original=original,
        club_timezone=MOSCOW,
    )

    assert result == datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert result.astimezone(MOSCOW) == datetime(
        2026,
        9,
        18,
        15,
        0,
        tzinfo=MOSCOW,
    )


@pytest.mark.parametrize(
    "value",
    ["18-09-2026", "18.9.2026", "31.02.2026", "18.09.26", ""],
)
def test_corrected_expiration_rejects_invalid_date(value: str) -> None:
    assert (
        parse_corrected_expires_at(
            value,
            original=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
            club_timezone=MOSCOW,
        )
        is None
    )


def test_corrected_expiration_rejects_naive_original() -> None:
    assert (
        parse_corrected_expires_at(
            "18.09.2026",
            original=datetime(2026, 10, 3, 15, 0),
            club_timezone=MOSCOW,
        )
        is None
    )


def test_latest_card_shows_persisted_cancelled_subscription() -> None:
    text = format_latest_subscription_card(
        GetLatestAthleteSubscriptionResult(
            athlete_id=7,
            athlete_full_name="Иван Иванов",
            latest=LatestSubscriptionDetails(
                subscription_id=19,
                plan_name="12 занятий",
                is_unlimited=False,
                access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
                group=MySubscriptionGroup(
                    training_group_id=3,
                    direction_name="Бокс",
                    group_name="Взрослые",
                ),
                starts_at=datetime(2026, 8, 1, 9, tzinfo=UTC),
                expires_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
                remaining_visits=0,
                status=SubscriptionStatus.CANCELLED,
            ),
        ),
        MOSCOW,
    )

    assert "Иван Иванов" in text
    assert "12 занятий" in text
    assert "Бокс · Взрослые" in text
    assert "01.08.2026 – 01.09.2026" in text
    assert "Осталось посещений:\n0" in text
    assert "Статус:\nОтменён" in text


def test_no_subscription_card_has_no_correction_action() -> None:
    text = format_latest_subscription_card(
        GetLatestAthleteSubscriptionResult(
            athlete_id=7,
            athlete_full_name="Иван Иванов",
            latest=None,
        ),
        MOSCOW,
    )

    assert NO_SUBSCRIPTION_TEXT in text
    assert all(
        callback_data
        != SubscriptionCorrectionCallback(
            action=SubscriptionCorrectionAction.BEGIN,
            value="0",
        ).pack()
        for callback_data in callback_texts(_card_keyboard(has_subscription=False))
    )


def test_remaining_visits_action_is_hidden_for_unlimited_draft() -> None:
    texts = callback_texts(_draft_keyboard(is_unlimited=True))

    assert "Остаток посещений" not in texts.values()
    assert "Дата окончания" in texts.values()
    assert "Статус" in texts.values()
