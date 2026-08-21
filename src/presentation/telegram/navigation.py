from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BACK_BUTTON_TEXT = "← Назад"
CANCEL_BUTTON_TEXT = "Отмена"
MENU_BUTTON_TEXT = "В меню"


class NavigationAction(StrEnum):
    BACK = "back"
    CANCEL = "cancel"


class NavigationTarget(StrEnum):
    MENU = "menu"
    USERS_LIST = "users"
    USER_PROFILE = "user"
    ATHLETE_LINK_LIST = "athlete_link"


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


def build_cancel_button() -> InlineKeyboardButton:
    return _build_navigation_button(
        text=CANCEL_BUTTON_TEXT,
        action=NavigationAction.CANCEL,
        target=NavigationTarget.MENU,
    )


def build_menu_button() -> InlineKeyboardButton:
    return _build_navigation_button(
        text=MENU_BUTTON_TEXT,
        action=NavigationAction.BACK,
        target=NavigationTarget.MENU,
    )


def build_single_button_keyboard(
    button: InlineKeyboardButton,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def _build_navigation_button(
    *,
    text: str,
    action: NavigationAction,
    target: NavigationTarget,
    target_id: int | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=NavigationCallback(
            action=action,
            target=target,
            target_id=target_id,
        ).pack(),
    )
