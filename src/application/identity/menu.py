from collections.abc import Iterable

from application.identity.dto import MenuContext, MenuItem
from domain.identity import SystemRoleCode

_ROLE_ORDER = (
    SystemRoleCode.ADMINISTRATOR,
    SystemRoleCode.TRAINER,
    SystemRoleCode.ATHLETE,
)

_ROLE_MENU_ITEMS = {
    SystemRoleCode.ADMINISTRATOR: (
        MenuItem(
            action_id="administrator.home",
            title="Меню администратора",
        ),
        MenuItem(
            action_id="administrator.link_athlete_account",
            title="Связать аккаунт",
        ),
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
    ),
}


def build_menu_context(
    role_codes: Iterable[SystemRoleCode],
) -> MenuContext:
    available_roles = set(role_codes)
    items = tuple(
        item
        for role_code in _ROLE_ORDER
        if role_code in available_roles
        for item in _ROLE_MENU_ITEMS[role_code]
    )
    return MenuContext(items=items)
