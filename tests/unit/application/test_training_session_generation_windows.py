from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from application.training_sessions import (
    TrainingSessionGenerationWindowResolver,
)

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FrozenClock:
    def __init__(self, current_time: datetime) -> None:
        self._current_time = current_time

    def now(self) -> datetime:
        return self._current_time


@pytest.mark.parametrize(
    "current_time",
    [
        datetime(2026, 8, 24, 8, 0, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 26, 11, 40, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 29, 23, 0, tzinfo=CLUB_TIMEZONE),
    ],
)
def test_bootstrap_window_materializes_full_current_working_week(
    current_time: datetime,
) -> None:
    resolver = TrainingSessionGenerationWindowResolver(
        FrozenClock(current_time),
        CLUB_TIMEZONE,
    )

    window = resolver.bootstrap_window()

    assert window.date_from == date(2026, 8, 24)
    assert window.date_to == date(2026, 8, 29)


def test_sunday_bootstrap_window_materializes_next_working_week() -> None:
    resolver = TrainingSessionGenerationWindowResolver(
        FrozenClock(
            datetime(2026, 8, 30, 12, 0, tzinfo=CLUB_TIMEZONE)
        ),
        CLUB_TIMEZONE,
    )

    window = resolver.bootstrap_window()

    assert window.date_from == date(2026, 8, 31)
    assert window.date_to == date(2026, 9, 5)


def test_scheduled_window_uses_next_monday_to_saturday() -> None:
    resolver = TrainingSessionGenerationWindowResolver(
        FrozenClock(
            datetime(2026, 8, 30, 0, 0, tzinfo=CLUB_TIMEZONE)
        ),
        CLUB_TIMEZONE,
    )

    window = resolver.next_week_window()

    assert window.date_from == date(2026, 8, 31)
    assert window.date_to == date(2026, 9, 5)


def test_window_uses_club_local_date_not_utc_date() -> None:
    resolver = TrainingSessionGenerationWindowResolver(
        FrozenClock(datetime(2026, 8, 23, 21, 30, tzinfo=UTC)),
        CLUB_TIMEZONE,
    )

    window = resolver.bootstrap_window()

    assert window.date_from == date(2026, 8, 24)
    assert window.date_to == date(2026, 8, 29)
