from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)

BACK_BUTTON_TEXT = "← Назад"
CANCEL_BUTTON_TEXT = "Отмена"
MENU_BUTTON_TEXT = "В панель"


class NavigationAction(StrEnum):
    BACK = "back"
    CANCEL = "cancel"


class NavigationTarget(StrEnum):
    MENU = "menu"
    ROLE_SELECTOR = "role_selector"
    ROLE_PANEL = "role_panel"
    USERS_LIST = "users"
    USER_PROFILE = "user"
    ATHLETE_LINK_LIST = "athlete_link"
    TRAINING_GROUPS = "training_groups"
    TRAINER_CANDIDATES = "trainer_candidates"
    CREATE_ATHLETE_FIRST_NAME = "create_athlete_first_name"
    CREATE_ATHLETE_LAST_NAME = "create_athlete_last_name"
    CREATE_ATHLETE_BIRTH_DATE = "create_athlete_birth_date"


class NavigationCallback(CallbackData, prefix="navigation"):
    action: NavigationAction
    target: NavigationTarget
    target_id: int | None = None


def build_back_button(
    target: NavigationTarget,
    *,
    target_id: int | None = None,
) -> InlineKeyboardButton:
    return _build_navigation_button(
        text=BACK_BUTTON_TEXT,
        action=NavigationAction.BACK,
        target=target,
        target_id=target_id,
    )


def build_cancel_button(
    target: NavigationTarget = NavigationTarget.ROLE_PANEL,
) -> InlineKeyboardButton:
    return _build_navigation_button(
        text=CANCEL_BUTTON_TEXT,
        action=NavigationAction.CANCEL,
        target=target,
    )


def build_menu_button() -> InlineKeyboardButton:
    return _build_navigation_button(
        text=MENU_BUTTON_TEXT,
        action=NavigationAction.BACK,
        target=NavigationTarget.ROLE_PANEL,
    )


def build_single_button_keyboard(
    button: InlineKeyboardButton,
) -> InlineKeyboardMarkup:
    return build_inline_keyboard((button,))


def _build_navigation_button(
    *,
    text: str,
    action: NavigationAction,
    target: NavigationTarget,
    target_id: int | None = None,
) -> InlineKeyboardButton:
    return build_callback_button(
        text=text,
        callback_data=NavigationCallback(
            action=action,
            target=target,
            target_id=target_id,
        ).pack(),
    )
