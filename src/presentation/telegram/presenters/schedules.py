from collections import defaultdict
from datetime import date

from application.training_sessions import (
    GetCurrentWeekScheduleResult,
    ScheduleSessionItem,
)
from domain.club import TrainingSessionStatus
from presentation.telegram.navigation import (
    build_menu_button,
    build_single_button_keyboard,
)
from presentation.telegram.screen import TelegramScreen

TITLE = "Расписание"
EMPTY_SCHEDULE_TEXT = "На этой неделе тренировок нет."
NO_ACTIVE_SUBSCRIPTION_TEXT = "У вас нет активного абонемента."
ATHLETE_PROFILE_NOT_FOUND_TEXT = (
    "Профиль спортсмена не найден. Обратитесь к администратору."
)
ATHLETE_PERMISSION_DENIED_TEXT = "Действие доступно только спортсмену."
TRAINER_PERMISSION_DENIED_TEXT = "Действие доступно только тренеру."
ADMINISTRATIVE_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)

_WEEKDAYS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")


def build_schedule_screen(
    result: GetCurrentWeekScheduleResult,
) -> TelegramScreen:
    schedule = result.schedule
    if schedule is None:
        return _screen(f"{TITLE}\n\n{NO_ACTIVE_SUBSCRIPTION_TEXT}")
    if not schedule.sessions:
        return _screen(f"{TITLE}\n\n{EMPTY_SCHEDULE_TEXT}")

    sessions_by_date: dict[date, list[ScheduleSessionItem]] = defaultdict(
        list
    )
    for item in sorted(
        schedule.sessions,
        key=lambda session: (session.starts_at, session.id),
    ):
        sessions_by_date[item.starts_at.date()].append(item)

    sections: list[str] = [TITLE]
    for session_date, sessions in sessions_by_date.items():
        lines = [
            f"{_WEEKDAYS[session_date.weekday()]} · {session_date:%d.%m}"
        ]
        lines.extend(_format_session(item) for item in sessions)
        sections.append("\n".join(lines))
    return _screen("\n\n".join(sections))


def build_athlete_profile_not_found_screen() -> TelegramScreen:
    return _screen(f"{TITLE}\n\n{ATHLETE_PROFILE_NOT_FOUND_TEXT}")


def build_permission_denied_screen(message: str) -> TelegramScreen:
    return _screen(f"{TITLE}\n\n{message}")


def _format_session(item: ScheduleSessionItem) -> str:
    cancelled = (
        " · ОТМЕНЕНА"
        if item.status is TrainingSessionStatus.CANCELLED
        else ""
    )
    return (
        f"{item.starts_at:%H:%M}–{item.ends_at:%H:%M} · "
        f"{item.sport_direction_name} · {item.group_name}{cancelled}"
    )


def _screen(text: str) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        reply_markup=build_single_button_keyboard(build_menu_button()),
    )
