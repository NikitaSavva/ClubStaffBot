from dataclasses import dataclass

from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from application.identity import MenuContext
from presentation.telegram.presenters.menu import RolePanel

ROLE_SWITCH_ACTION = "presentation.switch_role"
ROLE_SWITCH_LABEL = "Сменить роль"


@dataclass(frozen=True, slots=True)
class RoleReplyAction:
    action_id: str
    label: str


_ACTIONS = {
    "administrator.create_athlete": RoleReplyAction(
        action_id="administrator.create_athlete",
        label="Добавить спортсмена",
    ),
    "administrator.manage_users": RoleReplyAction(
        action_id="administrator.manage_users",
        label="Пользователи",
    ),
    "administrator.link_athlete_account": RoleReplyAction(
        action_id="administrator.link_athlete_account",
        label="Связать аккаунт",
    ),
}

_ROLE_LAYOUT = {
    RolePanel.ADMINISTRATOR: (
        ("administrator.create_athlete",),
        (
            "administrator.manage_users",
            "administrator.link_athlete_account",
        ),
    ),
    RolePanel.TRAINER: (),
    RolePanel.ATHLETE: (),
}


class RoleReplyKeyboardBuilder:
    def build(
        self,
        context: MenuContext,
        role: RolePanel,
        *,
        is_multi_role: bool,
    ) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
        actions = self._available_actions(context, role)
        keyboard = [
            [KeyboardButton(text=action.label) for action in row]
            for row in actions
        ]
        if is_multi_role:
            keyboard.append([KeyboardButton(text=ROLE_SWITCH_LABEL)])
        if not keyboard:
            return ReplyKeyboardRemove()
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            is_persistent=True,
        )

    def resolve(
        self,
        context: MenuContext,
        role: RolePanel,
        *,
        is_multi_role: bool,
        text: str,
    ) -> RoleReplyAction | None:
        if is_multi_role and text == ROLE_SWITCH_LABEL:
            return RoleReplyAction(
                action_id=ROLE_SWITCH_ACTION,
                label=ROLE_SWITCH_LABEL,
            )
        return next(
            (
                action
                for row in self._available_actions(context, role)
                for action in row
                if action.label == text
            ),
            None,
        )

    @staticmethod
    def _available_actions(
        context: MenuContext,
        role: RolePanel,
    ) -> tuple[tuple[RoleReplyAction, ...], ...]:
        available_action_ids = {item.action_id for item in context.items}
        return tuple(
            tuple(
                _ACTIONS[action_id]
                for action_id in row
                if action_id in available_action_ids
            )
            for row in _ROLE_LAYOUT[role]
            if any(action_id in available_action_ids for action_id in row)
        )


def role_reply_labels() -> frozenset[str]:
    return frozenset(
        (action.label for action in _ACTIONS.values()),
    ) | {ROLE_SWITCH_LABEL}
