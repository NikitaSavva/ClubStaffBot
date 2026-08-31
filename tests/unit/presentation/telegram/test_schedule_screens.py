from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from application.training_sessions import (
    GetCurrentWeekScheduleResult,
    ScheduleSessionItem,
    ScheduleWeek,
)
from domain.club import TrainingSessionStatus
from presentation.telegram.navigation import MENU_BUTTON_TEXT
from presentation.telegram.presenters.schedules import (
    ATHLETE_PROFILE_NOT_FOUND_TEXT,
    EMPTY_SCHEDULE_TEXT,
    NO_ACTIVE_SUBSCRIPTION_TEXT,
    build_athlete_profile_not_found_screen,
    build_schedule_screen,
)

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
MONDAY = datetime(2026, 8, 24, tzinfo=CLUB_TIMEZONE)
SUNDAY = datetime(2026, 8, 30, tzinfo=CLUB_TIMEZONE)


def item(
    session_id: int,
    starts_at: datetime,
    *,
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
    group_name: str = "Взрослые",
) -> ScheduleSessionItem:
    return ScheduleSessionItem(
        id=session_id,
        training_group_id=session_id + 100,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=90),
        status=status,
        sport_direction_name="Кикбоксинг",
        group_name=group_name,
    )


def result(
    sessions: tuple[ScheduleSessionItem, ...],
) -> GetCurrentWeekScheduleResult:
    return GetCurrentWeekScheduleResult(
        schedule=ScheduleWeek(
            week_start=MONDAY,
            week_end=SUNDAY,
            sessions=sessions,
        )
    )


def menu_button_text(screen_text_result: GetCurrentWeekScheduleResult) -> str:
    screen = build_schedule_screen(screen_text_result)
    assert screen.reply_markup is not None
    return screen.reply_markup.inline_keyboard[0][0].text


def test_schedule_groups_and_sorts_days_and_marks_cancelled() -> None:
    screen = build_schedule_screen(
        result(
            (
                item(3, MONDAY + timedelta(days=2, hours=19)),
                item(
                    2,
                    MONDAY + timedelta(hours=19),
                    status=TrainingSessionStatus.CANCELLED,
                ),
                item(
                    1,
                    MONDAY + timedelta(hours=9),
                    status=TrainingSessionStatus.COMPLETED,
                    group_name="Дети 9–14 лет",
                ),
            )
        )
    )

    assert screen.text == (
        "Расписание\n\n"
        "ПН · 24.08\n"
        "09:00–10:30 · Кикбоксинг · Дети 9–14 лет\n"
        "19:00–20:30 · Кикбоксинг · Взрослые · ОТМЕНЕНА\n\n"
        "СР · 26.08\n"
        "19:00–20:30 · Кикбоксинг · Взрослые"
    )
    assert screen.text.count("ПН · 24.08") == 1
    assert "COMPLETED" not in screen.text
    assert screen.banner is None
    assert menu_button_text(result(())) == MENU_BUTTON_TEXT


def test_empty_and_no_subscription_are_different_normal_states() -> None:
    empty = build_schedule_screen(result(()))
    no_subscription = build_schedule_screen(
        GetCurrentWeekScheduleResult(schedule=None)
    )

    assert empty.text == f"Расписание\n\n{EMPTY_SCHEDULE_TEXT}"
    assert no_subscription.text == (
        f"Расписание\n\n{NO_ACTIVE_SUBSCRIPTION_TEXT}"
    )


def test_missing_athlete_profile_is_controlled_text_only_screen() -> None:
    screen = build_athlete_profile_not_found_screen()

    assert screen.text == f"Расписание\n\n{ATHLETE_PROFILE_NOT_FOUND_TEXT}"
    assert screen.banner is None


def test_seed_sized_schedule_fits_single_text_message() -> None:
    sessions = tuple(
        item(
            session_id=index + 1,
            starts_at=MONDAY
            + timedelta(days=index % 6, hours=8 + index % 12),
            group_name=f"Группа {index + 1}",
        )
        for index in range(32)
    )

    screen = build_schedule_screen(result(sessions))

    assert len(screen.text) < 4096
    assert screen.banner is None
