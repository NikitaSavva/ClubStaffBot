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
        action_id="administrator.scan_qr",
        title="Сканировать QR",
    ),
    MenuItem(
        action_id="administrator.confirm_attendance",
        title="Отметить вход",
    ),
    MenuItem(
        action_id="administrator.schedule",
        title="Расписание",
    ),
    MenuItem(
        action_id="administrator.activate_subscription",
        title="Выдать абонемент",
    ),
    MenuItem(
        action_id="administrator.view_subscription",
        title="Посмотреть абонемент",
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
        MenuItem(
            action_id="trainer.schedule",
            title="Расписание",
        ),
    ),
    SystemRoleCode.ATHLETE: (
        MenuItem(
            action_id="athlete.home",
            title="Меню спортсмена",
        ),
        MenuItem(
            action_id="athlete.my_qr",
            title="Мой QR",
        ),
        MenuItem(
            action_id="athlete.schedule",
            title="Расписание",
        ),
        MenuItem(
            action_id="athlete.my_subscription",
            title="Мой абонемент",
        ),
    ),
}


def build_menu_context(
    role_codes: Iterable[SystemRoleCode],
    *,
    scanner_webapp_url: str,
) -> MenuContext:
    available_roles = set(role_codes)
    items_by_action_id = {
        item.action_id: item
        for role_code in _ROLE_ORDER
        if role_code in available_roles
        for item in _ROLE_MENU_ITEMS[role_code]
    }
    items = tuple(
        MenuItem(
            action_id=item.action_id,
            title=item.title,
            web_app_url=(
                scanner_webapp_url
                if item.action_id == "administrator.scan_qr"
                else None
            ),
        )
        for item in items_by_action_id.values()
    )
    return MenuContext(items=items)
