from datetime import time

import pytest

from application.club import ScheduleRuleSummary, TrainingGroupSummary
from domain.club import TrainingGroupType
from presentation.telegram.presenters.training_groups import (
    format_training_group_button_label,
    format_training_group_details,
    format_training_group_label,
)


def group(
    *,
    group_id: int,
    name: str,
    weekdays: tuple[int, ...],
    start_time: time,
    end_time: time,
    direction_name: str = "Кикбоксинг",
    direction_short_name: str | None = "K1",
) -> TrainingGroupSummary:
    return TrainingGroupSummary(
        training_group_id=group_id,
        direction_name=direction_name,
        direction_short_name=direction_short_name,
        group_name=name,
        group_type=TrainingGroupType.REGULAR,
        schedule_rules=tuple(
            ScheduleRuleSummary(
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )
            for weekday in weekdays
        ),
        trainer=None,
    )


@pytest.mark.parametrize(
    (
        "direction_name",
        "direction_short_name",
        "name",
        "starts_at",
        "expected",
    ),
    [
        ("Кикбоксинг", "K1", "Взрослые", time(19), "K1 · Взрослые · 19:00"),
        ("Кикбоксинг", "K1", "Взрослые", time(8, 30), "K1 · Взрослые · 08:30"),
        ("Кикбоксинг", "K1", "Девушки", time(10), "K1 · Девушки · 10:00"),
        ("Кикбоксинг", "K1", "Девушки", time(18, 45), "K1 · Девушки · 18:45"),
        ("MMA", "MMA", "Взрослые", time(20), "MMA · Взрослые · 20:00"),
    ],
)
def test_button_label_uses_compact_direction_group_and_start_time(
    direction_name: str,
    direction_short_name: str | None,
    name: str,
    starts_at: time,
    expected: str,
) -> None:
    training_group = group(
        group_id=1,
        name=name,
        weekdays=(0,),
        start_time=starts_at,
        end_time=time(21),
        direction_name=direction_name,
        direction_short_name=direction_short_name,
    )

    assert format_training_group_button_label(training_group) == expected


def test_button_label_falls_back_to_full_direction_name() -> None:
    training_group = group(
        group_id=1,
        name="Взрослые",
        weekdays=(0,),
        start_time=time(18),
        end_time=time(19),
        direction_name="Бокс",
        direction_short_name=None,
    )

    assert format_training_group_button_label(training_group) == (
        "Бокс · Взрослые · 18:00"
    )


@pytest.mark.parametrize(
    ("direction_name", "direction_short_name", "expected"),
    [
        (
            "Кикбоксинг",
            "K1",
            "K1 · Взрослые — ПН/СР/ПТ 19:00",
        ),
        (
            "MMA",
            "MMA",
            "MMA · Взрослые — ПН/СР/ПТ 19:00",
        ),
        (
            "Бокс",
            None,
            "Бокс · Взрослые — ПН/СР/ПТ 19:00",
        ),
    ],
)
def test_full_button_label_uses_short_direction_with_name_fallback(
    direction_name: str,
    direction_short_name: str | None,
    expected: str,
) -> None:
    training_group = group(
        group_id=1,
        name="Взрослые",
        weekdays=(0, 2, 4),
        start_time=time(19),
        end_time=time(20, 30),
        direction_name=direction_name,
        direction_short_name=direction_short_name,
    )

    assert format_training_group_label(training_group) == expected


def test_group_details_include_full_name_weekdays_and_end_time() -> None:
    training_group = group(
        group_id=1,
        name="Взрослые",
        weekdays=(0, 2, 4),
        start_time=time(19, 0),
        end_time=time(20, 30),
    )

    assert format_training_group_details(training_group) == (
        "Кикбоксинг · Взрослые\nПН/СР/ПТ 19:00–20:30"
    )


def test_consecutive_club_days_are_compacted_in_full_details() -> None:
    training_group = group(
        group_id=1,
        name="Сборная",
        weekdays=(0, 1, 2, 3, 4, 5),
        start_time=time(16, 0),
        end_time=time(17, 30),
    )

    assert format_training_group_details(training_group) == (
        "Кикбоксинг · Сборная\nПН–СБ 16:00–17:30"
    )
