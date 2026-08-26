from datetime import UTC, date, datetime, time
from decimal import Decimal

from application.athletes import AthleteSummary
from application.club import ScheduleRuleSummary, TrainingGroupSummary
from application.subscriptions import (
    ActivateSubscriptionResult,
    SubscriptionPlanSummary,
)
from domain.club import TrainingGroupType
from domain.subscriptions import SubscriptionAccessScope
from presentation.telegram.handlers.subscription_activation import (
    CONFIRM_ACTIVATION_ACTION,
    SELECT_GROUP_PREFIX,
    _applicable_groups,
    _confirmation_text,
    _success_text,
    build_activation_confirmation_keyboard,
    build_group_selection_keyboard,
    format_subscription_plan_label,
)


def plan(
    *,
    access_scope: SubscriptionAccessScope = (
        SubscriptionAccessScope.SPECIFIC_GROUP
    ),
    required_group_type: TrainingGroupType | None = None,
    visit_limit: int | None = 12,
) -> SubscriptionPlanSummary:
    return SubscriptionPlanSummary(
        subscription_plan_id=1,
        name="12 посещений" if visit_limit is not None else "Безлимит",
        price=Decimal("6000") if visit_limit is not None else Decimal("10000"),
        duration_months=1,
        visit_limit=visit_limit,
        access_scope=access_scope,
        required_group_type=required_group_type,
    )


def group(
    group_id: int,
    group_type: TrainingGroupType,
) -> TrainingGroupSummary:
    return TrainingGroupSummary(
        training_group_id=group_id,
        direction_name="Кикбоксинг",
        group_name=(
            "Мини-группа"
            if group_type is TrainingGroupType.MINI
            else "Взрослые"
        ),
        group_type=group_type,
        schedule_rules=(
            ScheduleRuleSummary(
                weekday=0,
                start_time=time(19),
                end_time=time(20, 30),
            ),
        ),
        trainer=None,
    )


ATHLETE = AthleteSummary(
    athlete_id=3,
    first_name="Иван",
    last_name="Иванов",
    birth_date=date(1991, 12, 27),
)


def test_plan_label_formats_price_for_button() -> None:
    assert format_subscription_plan_label(plan()) == (
        "12 посещений — 6 000 ₽"
    )


def test_specific_group_confirmation_contains_group_schedule() -> None:
    text = _confirmation_text(
        ATHLETE,
        plan(),
        group(10, TrainingGroupType.REGULAR),
    )

    assert text.startswith("Выдать абонемент?")
    assert "Иван Иванов" in text
    assert "Кикбоксинг · Взрослые" in text
    assert "ПН 19:00–20:30" in text
    assert "Посещений:\n12" in text


def test_unlimited_confirmation_skips_group_and_excludes_mini() -> None:
    unlimited = plan(
        access_scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
        visit_limit=None,
    )

    text = _confirmation_text(ATHLETE, unlimited, None)

    assert "Все обычные группы клуба" in text
    assert "Мини-группы:\nНе входят" in text
    assert "Посещений:\nБез ограничений" in text
    callbacks = {
        button.callback_data
        for row in build_activation_confirmation_keyboard(
            unlimited
        ).inline_keyboard
        for button in row
    }
    assert CONFIRM_ACTIVATION_ACTION in callbacks


def test_mini_plan_keyboard_contains_only_mini_groups() -> None:
    groups = (
        group(10, TrainingGroupType.REGULAR),
        group(11, TrainingGroupType.MINI),
    )
    mini_plan = plan(required_group_type=TrainingGroupType.MINI)

    applicable = _applicable_groups(groups, mini_plan)
    keyboard = build_group_selection_keyboard(applicable)
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert applicable == (groups[1],)
    assert f"{SELECT_GROUP_PREFIX}11" in callbacks
    assert f"{SELECT_GROUP_PREFIX}10" not in callbacks


def test_generic_specific_plan_keeps_regular_and_mini_groups() -> None:
    groups = (
        group(10, TrainingGroupType.REGULAR),
        group(11, TrainingGroupType.MINI),
    )

    assert _applicable_groups(groups, plan()) == groups


def test_success_formats_native_dates_and_unlimited_visits() -> None:
    result = ActivateSubscriptionResult(
        subscription_id=5,
        athlete_id=ATHLETE.athlete_id,
        athlete_full_name=ATHLETE.full_name,
        subscription_plan_id=1,
        plan_name="Безлимит",
        training_group_id=None,
        starts_at=datetime(2026, 8, 26, 12, tzinfo=UTC),
        expires_at=datetime(2026, 9, 26, 12, tzinfo=UTC),
        remaining_visits=None,
    )

    text = _success_text(result, None)

    assert text.startswith("Абонемент активирован")
    assert "26.08.2026 – 26.09.2026" in text
    assert "Осталось посещений:\nБез ограничений" in text
