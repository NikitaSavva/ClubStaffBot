from collections.abc import Iterable

from application.identity.dto import MenuContext, MenuItem
from domain.identity import SystemRoleCode

_ROLE_ORDER = (
    SystemRoleCode.OWNER,
    SystemRoleCode.ADMINISTRATOR,
    SystemRoleCode.TRAINER,
    SystemRoleCode.ATHLETE,
)

_ADMINISTRATIVE_MENU_ITEMS = (
    MenuItem(
        action_id="administrator.activate_subscription",
        title="Выдать абонемент",
    ),
    MenuItem(
        action_id="administrator.create_athlete",
        title="Добавить спортсмена",
    ),
    MenuItem(
        action_id="administrator.link_athlete_account",
        title="Связать аккаунт",
    ),
    MenuItem(
        action_id="administrator.assign_trainer",
        title="Назначить тренера",
    ),
    MenuItem(
        action_id="administrator.manage_users",
        title="Пользователи",
    ),
)

_ROLE_MENU_ITEMS = {
    SystemRoleCode.OWNER: (
        MenuItem(
            action_id="owner.home",
            title="Меню владельца",
        ),
        *_ADMINISTRATIVE_MENU_ITEMS,
    ),
    SystemRoleCode.ADMINISTRATOR: (
        MenuItem(
            action_id="administrator.home",
            title="Меню администратора",
        ),
        *_ADMINISTRATIVE_MENU_ITEMS,
    ),
    SystemRoleCode.TRAINER: (
        MenuItem(
            action_id="trainer.home",
            title="Меню тренера",
        ),
    ),
    SystemRoleCode.ATHLETE: (
        MenuItem(
            action_id="athlete.home",
            title="Меню спортсмена",
        ),
        MenuItem(
            action_id="athlete.my_subscription",
            title="Мой абонемент",
        ),
    ),
}


def build_menu_context(
    role_codes: Iterable[SystemRoleCode],
) -> MenuContext:
    available_roles = set(role_codes)
    items_by_action_id = {
        item.action_id: item
        for role_code in _ROLE_ORDER
        if role_code in available_roles
        for item in _ROLE_MENU_ITEMS[role_code]
    }
    return MenuContext(items=tuple(items_by_action_id.values()))
