from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from application.identity import MenuContext, MenuItem
from presentation.telegram.keyboards.role import (
    ROLE_SWITCH_ACTION,
    ROLE_SWITCH_LABEL,
    RoleReplyKeyboardBuilder,
)
from presentation.telegram.presenters import RolePanel


def menu_context(*action_ids: str) -> MenuContext:
    return MenuContext(
        items=tuple(
            MenuItem(action_id=action_id, title=f"Title for {action_id}")
            for action_id in action_ids
        )
    )


def keyboard_labels(markup: ReplyKeyboardMarkup) -> list[list[str]]:
    return [
        [button.text for button in row]
        for row in markup.keyboard
    ]


def test_administrator_keyboard_uses_allowed_menu_actions_and_compact_layout(
) -> None:
    builder = RoleReplyKeyboardBuilder()

    markup = builder.build(
        menu_context(
            "administrator.home",
            "administrator.create_athlete",
            "administrator.manage_users",
            "administrator.link_athlete_account",
            "athlete.home",
        ),
        RolePanel.ADMINISTRATOR,
        is_multi_role=False,
    )

    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.resize_keyboard is True
    assert markup.is_persistent is True
    assert markup.one_time_keyboard is None
    assert keyboard_labels(markup) == [
        ["Добавить спортсмена"],
        ["Пользователи", "Связать аккаунт"],
    ]


def test_missing_menu_actions_are_not_rendered() -> None:
    builder = RoleReplyKeyboardBuilder()

    markup = builder.build(
        menu_context(
            "administrator.home",
            "administrator.manage_users",
        ),
        RolePanel.ADMINISTRATOR,
        is_multi_role=False,
    )

    assert isinstance(markup, ReplyKeyboardMarkup)
    assert keyboard_labels(markup) == [["Пользователи"]]


def test_multi_role_keyboard_adds_role_switch_action() -> None:
    builder = RoleReplyKeyboardBuilder()

    markup = builder.build(
        menu_context("athlete.home", "administrator.home"),
        RolePanel.ATHLETE,
        is_multi_role=True,
    )

    assert isinstance(markup, ReplyKeyboardMarkup)
    assert keyboard_labels(markup) == [[ROLE_SWITCH_LABEL]]
    resolved = builder.resolve(
        menu_context("athlete.home", "administrator.home"),
        RolePanel.ATHLETE,
        is_multi_role=True,
        text=ROLE_SWITCH_LABEL,
    )
    assert resolved is not None
    assert resolved.action_id == ROLE_SWITCH_ACTION


def test_single_role_without_global_actions_removes_reply_keyboard() -> None:
    builder = RoleReplyKeyboardBuilder()

    markup = builder.build(
        menu_context("athlete.home"),
        RolePanel.ATHLETE,
        is_multi_role=False,
    )

    assert isinstance(markup, ReplyKeyboardRemove)
    assert (
        builder.resolve(
            menu_context("athlete.home"),
            RolePanel.ATHLETE,
            is_multi_role=False,
            text=ROLE_SWITCH_LABEL,
        )
        is None
    )


def test_resolver_uses_canonical_label_and_current_role_actions() -> None:
    builder = RoleReplyKeyboardBuilder()
    context = menu_context(
        "administrator.home",
        "administrator.manage_users",
        "athlete.home",
    )

    admin_action = builder.resolve(
        context,
        RolePanel.ADMINISTRATOR,
        is_multi_role=True,
        text="Пользователи",
    )
    athlete_action = builder.resolve(
        context,
        RolePanel.ATHLETE,
        is_multi_role=True,
        text="Пользователи",
    )

    assert admin_action is not None
    assert admin_action.action_id == "administrator.manage_users"
    assert athlete_action is None
