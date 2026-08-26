from datetime import date, timedelta
from zoneinfo import ZoneInfo

from application.common import Clock
from application.training_sessions.dto import GenerationWindow

SUNDAY = 6


class TrainingSessionGenerationWindowResolver:
    def __init__(self, clock: Clock, club_timezone: ZoneInfo) -> None:
        self._clock = clock
        self._club_timezone = club_timezone

    def bootstrap_window(self) -> GenerationWindow:
        current_date = self._local_current_date()
        current_week_monday = current_date - timedelta(
            days=current_date.weekday()
        )
        monday = (
            current_week_monday + timedelta(days=7)
            if current_date.weekday() == SUNDAY
            else current_week_monday
        )
        return _monday_to_saturday(monday)

    def next_week_window(self) -> GenerationWindow:
        current_date = self._local_current_date()
        current_week_monday = current_date - timedelta(
            days=current_date.weekday()
        )
        return _monday_to_saturday(current_week_monday + timedelta(days=7))

    def _local_current_date(self) -> date:
        return self._clock.now().astimezone(self._club_timezone).date()


def _monday_to_saturday(monday: date) -> GenerationWindow:
    return GenerationWindow(
        date_from=monday,
        date_to=monday + timedelta(days=5),
    )
