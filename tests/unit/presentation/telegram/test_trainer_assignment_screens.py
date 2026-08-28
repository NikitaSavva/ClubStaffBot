from datetime import time

from application.club import (
    ScheduleRuleSummary,
    TrainerSummary,
    TrainingGroupSummary,
)
from domain.club import TrainingGroupType
from presentation.telegram.handlers.trainer_assignment import (
    SELECT_GROUP_PREFIX,
    build_group_selection_keyboard,
    build_trainer_selection_screen,
)
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)


def test_empty_trainer_list_explains_state_without_creation_action() -> None:
    group = TrainingGroupSummary(
        training_group_id=42,
        direction_name="Кикбоксинг",
        direction_short_name="K1",
        group_name="Взрослые",
        group_type=TrainingGroupType.REGULAR,
        schedule_rules=(
            ScheduleRuleSummary(
                weekday=0,
                start_time=time(19, 0),
                end_time=time(20, 30),
            ),
        ),
        trainer=None,
    )

    screen = build_trainer_selection_screen(group, ())

    assert "В системе пока нет пользователей с ролью «Тренер»." in screen.text
    assert screen.reply_markup is not None
    callbacks = {
        button.callback_data
        for row in screen.reply_markup.inline_keyboard
        for button in row
    }
    assert callbacks == {
        NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.TRAINING_GROUPS,
        ).pack(),
        NavigationCallback(
            action=NavigationAction.CANCEL,
            target=NavigationTarget.ROLE_PANEL,
        ).pack(),
    }


def training_group(
    *,
    group_id: int,
    name: str,
    starts_at: time,
    weekdays: tuple[int, ...],
    trainer: TrainerSummary | None = None,
) -> TrainingGroupSummary:
    return TrainingGroupSummary(
        training_group_id=group_id,
        direction_name="Кикбоксинг",
        direction_short_name="K1",
        group_name=name,
        group_type=TrainingGroupType.REGULAR,
        schedule_rules=tuple(
            ScheduleRuleSummary(
                weekday=weekday,
                start_time=starts_at,
                end_time=time(21),
            )
            for weekday in weekdays
        ),
        trainer=trainer,
    )


def test_group_buttons_use_short_direction_and_keep_existing_semantics() -> None:
    assigned_trainer = TrainerSummary(
        user_id=7,
        first_name="Иван",
        last_name="Иванов",
        username=None,
    )
    groups = (
        training_group(
            group_id=1,
            name="Взрослые",
            starts_at=time(19),
            weekdays=(0, 2, 4),
        ),
        training_group(
            group_id=2,
            name="Взрослые",
            starts_at=time(8, 30),
            weekdays=(1, 3, 5),
        ),
        training_group(
            group_id=3,
            name="Девушки",
            starts_at=time(10),
            weekdays=(1, 3),
        ),
        training_group(
            group_id=4,
            name="Девушки",
            starts_at=time(18, 45),
            weekdays=(1, 3, 5),
            trainer=assigned_trainer,
        ),
    )

    keyboard = build_group_selection_keyboard(groups)
    labels = {
        button.callback_data: button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    assert labels[f"{SELECT_GROUP_PREFIX}1"] == (
        "K1 · Взрослые — ПН/СР/ПТ 19:00"
    )
    assert labels[f"{SELECT_GROUP_PREFIX}2"] == (
        "K1 · Взрослые — ВТ/ЧТ/СБ 08:30"
    )
    assert labels[f"{SELECT_GROUP_PREFIX}3"] == (
        "K1 · Девушки — ВТ/ЧТ 10:00"
    )
    assert labels[f"{SELECT_GROUP_PREFIX}4"] == (
        "✓ K1 · Девушки — ВТ/ЧТ/СБ 18:45"
    )
