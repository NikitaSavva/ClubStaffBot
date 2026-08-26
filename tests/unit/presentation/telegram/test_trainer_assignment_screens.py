from datetime import time

from application.club import ScheduleRuleSummary, TrainingGroupSummary
from domain.club import TrainingGroupType
from presentation.telegram.handlers.trainer_assignment import (
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
