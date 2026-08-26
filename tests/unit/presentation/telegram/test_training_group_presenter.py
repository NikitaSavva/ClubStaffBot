from datetime import time

import pytest

from application.club import ScheduleRuleSummary, TrainingGroupSummary
from domain.club import TrainingGroupType
from presentation.telegram.presenters.training_groups import (
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
) -> TrainingGroupSummary:
    return TrainingGroupSummary(
        training_group_id=group_id,
        direction_name="Кикбоксинг",
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


@pytest.mark.parametrize("name", ["Взрослые", "Девушки"])
def test_duplicate_group_names_have_distinct_composite_labels(
    name: str,
) -> None:
    first = group(
        group_id=1,
        name=name,
        weekdays=(0, 2, 4),
        start_time=time(19, 0),
        end_time=time(20, 30),
    )
    second = group(
        group_id=2,
        name=name,
        weekdays=(1, 3, 5),
        start_time=time(8, 30),
        end_time=time(10, 0),
    )

    first_label = format_training_group_label(first)
    second_label = format_training_group_label(second)

    assert first_label == f"Кикбоксинг · {name} — ПН/СР/ПТ 19:00"
    assert second_label == f"Кикбоксинг · {name} — ВТ/ЧТ/СБ 08:30"
    assert first_label != second_label


def test_group_details_include_schedule_end_time() -> None:
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


def test_consecutive_club_days_are_compacted() -> None:
    training_group = group(
        group_id=1,
        name="Сборная",
        weekdays=(0, 1, 2, 3, 4, 5),
        start_time=time(16, 0),
        end_time=time(17, 30),
    )

    assert format_training_group_label(training_group) == (
        "Кикбоксинг · Сборная — ПН–СБ 16:00"
    )
