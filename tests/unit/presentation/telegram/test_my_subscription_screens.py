from datetime import UTC, datetime

import pytest

from application.identity import MenuContext, MenuItem
from application.subscriptions import (
    GetMySubscriptionResult,
    MySubscriptionDetails,
    MySubscriptionGroup,
)
from domain.subscriptions import SubscriptionAccessScope
from presentation.telegram.navigation import MENU_BUTTON_TEXT
from presentation.telegram.presenters.menu import (
    RolePanel,
    build_role_panel_screen,
)
from presentation.telegram.presenters.subscriptions import (
    ATHLETE_PROFILE_NOT_FOUND_TEXT,
    NO_ACTIVE_SUBSCRIPTION_TEXT,
    build_athlete_profile_not_found_screen,
    build_my_subscription_screen,
)
from presentation.telegram.screen import BannerContext, TelegramScreen

STARTS_AT = datetime(2026, 8, 26, 12, tzinfo=UTC)
EXPIRES_AT = datetime(2026, 9, 26, 12, tzinfo=UTC)


def limited_details(
    *,
    plan_name: str = "12 посещений",
    group_name: str = "Взрослые",
    remaining_visits: int = 7,
) -> MySubscriptionDetails:
    return MySubscriptionDetails(
        plan_name=plan_name,
        is_unlimited=False,
        access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        group=MySubscriptionGroup(
            training_group_id=1,
            direction_name="Кикбоксинг",
            group_name=group_name,
        ),
        starts_at=STARTS_AT,
        expires_at=EXPIRES_AT,
        remaining_visits=remaining_visits,
    )


def button_text(screen: TelegramScreen) -> str:
    assert screen.reply_markup is not None
    return screen.reply_markup.inline_keyboard[0][0].text


def test_limited_screen_contains_stored_remaining_and_simple_group() -> None:
    screen = build_my_subscription_screen(
        GetMySubscriptionResult(current=limited_details())
    )

    assert screen.text == (
        "Мой абонемент\n\n"
        "Тариф:\n12 посещений\n\n"
        "Группа:\nКикбоксинг · Взрослые\n\n"
        "Действует:\n26.08.2026 – 26.09.2026\n\n"
        "Осталось посещений:\n7"
    )
    assert "ПН" not in screen.text
    assert screen.banner is BannerContext.ATHLETE_PANEL
    assert button_text(screen) == MENU_BUTTON_TEXT


def test_mini_uses_the_same_specific_group_representation() -> None:
    screen = build_my_subscription_screen(
        GetMySubscriptionResult(
            current=limited_details(
                plan_name="Мини-группа",
                group_name="Мини-группа",
            )
        )
    )

    assert "Тариф:\nМини-группа" in screen.text
    assert "Группа:\nКикбоксинг · Мини-группа" in screen.text


def test_zero_remaining_visits_is_rendered_as_zero() -> None:
    screen = build_my_subscription_screen(
        GetMySubscriptionResult(
            current=limited_details(remaining_visits=0)
        )
    )

    assert screen.text.endswith("Осталось посещений:\n0")
    assert "Без ограничений" not in screen.text


def test_unlimited_screen_describes_regular_access_and_mini_exclusion() -> None:
    screen = build_my_subscription_screen(
        GetMySubscriptionResult(
            current=MySubscriptionDetails(
                plan_name="Безлимит",
                is_unlimited=True,
                access_scope=(
                    SubscriptionAccessScope.ALL_REGULAR_GROUPS
                ),
                group=None,
                starts_at=STARTS_AT,
                expires_at=EXPIRES_AT,
                remaining_visits=None,
            )
        )
    )

    assert screen.text == (
        "Мой абонемент\n\n"
        "Тариф:\nБезлимит\n\n"
        "Доступ:\nВсе обычные группы клуба\n\n"
        "Мини-группы:\nНе входят\n\n"
        "Действует:\n26.08.2026 – 26.09.2026\n\n"
        "Посещения:\nБез ограничений"
    )


def test_no_active_screen_contains_no_historical_details() -> None:
    screen = build_my_subscription_screen(
        GetMySubscriptionResult(current=None)
    )

    assert screen.text == f"Мой абонемент\n\n{NO_ACTIVE_SUBSCRIPTION_TEXT}"
    assert "Тариф:" not in screen.text
    assert button_text(screen) == MENU_BUTTON_TEXT


def test_missing_profile_screen_is_controlled() -> None:
    screen = build_athlete_profile_not_found_screen()

    assert screen.text == f"Мой абонемент\n\n{ATHLETE_PROFILE_NOT_FOUND_TEXT}"
    assert button_text(screen) == MENU_BUTTON_TEXT


@pytest.mark.parametrize(
    "role",
    [RolePanel.OWNER, RolePanel.ADMINISTRATOR, RolePanel.TRAINER],
)
def test_other_role_panels_do_not_show_athlete_self_service_action(
    role: RolePanel,
) -> None:
    context = MenuContext(
        items=(
            MenuItem(action_id="owner.home", title="Меню владельца"),
            MenuItem(
                action_id="administrator.home",
                title="Меню администратора",
            ),
            MenuItem(action_id="trainer.home", title="Меню тренера"),
            MenuItem(action_id="athlete.home", title="Меню спортсмена"),
            MenuItem(
                action_id="athlete.my_subscription",
                title="Мой абонемент",
            ),
        )
    )

    screen = build_role_panel_screen(
        context,
        role,
        show_role_selector_back=False,
    )

    assert screen.reply_markup is not None
    callback_data = {
        button.callback_data
        for row in screen.reply_markup.inline_keyboard
        for button in row
    }
    assert "athlete.my_subscription" not in callback_data


def test_athlete_panel_shows_my_subscription_action() -> None:
    context = MenuContext(
        items=(
            MenuItem(action_id="athlete.home", title="Меню спортсмена"),
            MenuItem(action_id="athlete.my_qr", title="Мой QR"),
            MenuItem(action_id="athlete.schedule", title="Расписание"),
            MenuItem(
                action_id="athlete.my_subscription",
                title="Мой абонемент",
            ),
        )
    )

    screen = build_role_panel_screen(
        context,
        RolePanel.ATHLETE,
        show_role_selector_back=False,
    )

    assert screen.reply_markup is not None
    assert screen.reply_markup.inline_keyboard[2][0].callback_data == (
        "athlete.my_subscription"
    )
