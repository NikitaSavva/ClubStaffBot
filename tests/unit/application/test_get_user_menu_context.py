from datetime import UTC, datetime

import pytest

from application.identity import (
    GetUserMenuContextInteractor,
    GetUserMenuContextQuery,
    MenuContext,
    MenuItem,
)
from application.identity.errors import UserHasNoRolesError, UserNotFoundError
from domain.identity import SystemRoleCode, User

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
TELEGRAM_ID = 123456
SCANNER_URL = "https://scanner.example.test/webapp/scanner"


class FakeUserRepository:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.requested_telegram_ids: list[int] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        self.requested_telegram_ids.append(telegram_id)
        return self.user


class FakeRoleRepository:
    def __init__(self, role_codes: tuple[SystemRoleCode, ...]) -> None:
        self.role_codes = role_codes
        self.requested_user_ids: list[int] = []

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        self.requested_user_ids.append(user_id)
        return self.role_codes


def registered_user() -> User:
    return User(
        id=101,
        telegram_id=TELEGRAM_ID,
        username="menu_user",
        first_name="Menu",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def build_interactor(
    *,
    user: User | None = None,
    role_codes: tuple[SystemRoleCode, ...] = (),
) -> tuple[
    GetUserMenuContextInteractor,
    FakeUserRepository,
    FakeRoleRepository,
]:
    users = FakeUserRepository(user if user is not None else registered_user())
    roles = FakeRoleRepository(role_codes)
    return (
        GetUserMenuContextInteractor(
            user_repository=users,
            role_repository=roles,
            scanner_webapp_url=SCANNER_URL,
        ),
        users,
        roles,
    )


@pytest.mark.parametrize(
    ("role_code", "expected_items"),
    [
        (
            SystemRoleCode.OWNER,
            (
                    MenuItem(
                        action_id="owner.home",
                        title="Меню владельца",
                    ),
                    MenuItem(
                        action_id="administrator.scan_qr",
                        title="Сканировать QR",
                        web_app_url=SCANNER_URL,
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
            ),
        ),
        (
            SystemRoleCode.ADMINISTRATOR,
            (
                    MenuItem(
                        action_id="administrator.home",
                        title="Меню администратора",
                    ),
                    MenuItem(
                        action_id="administrator.scan_qr",
                        title="Сканировать QR",
                        web_app_url=SCANNER_URL,
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
            ),
        ),
        (
            SystemRoleCode.ATHLETE,
            (
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
        ),
        (
            SystemRoleCode.TRAINER,
            (
                MenuItem(
                    action_id="trainer.home",
                    title="Меню тренера",
                ),
                MenuItem(
                    action_id="trainer.schedule",
                    title="Расписание",
                ),
            ),
        ),
    ],
)
async def test_role_receives_its_application_menu_item(
    role_code: SystemRoleCode,
    expected_items: tuple[MenuItem, ...],
) -> None:
    interactor, users, roles = build_interactor(role_codes=(role_code,))

    result = await interactor(GetUserMenuContextQuery(telegram_id=TELEGRAM_ID))

    assert result == MenuContext(items=expected_items)
    assert type(result) is MenuContext
    assert all(type(item) is MenuItem for item in result.items)
    assert users.requested_telegram_ids == [TELEGRAM_ID]
    assert roles.requested_user_ids == [101]


async def test_multiple_roles_produce_deduplicated_mode_entries() -> None:
    interactor, _, _ = build_interactor(
        role_codes=(
            SystemRoleCode.ATHLETE,
            SystemRoleCode.ADMINISTRATOR,
            SystemRoleCode.TRAINER,
            SystemRoleCode.ADMINISTRATOR,
        )
    )

    result = await interactor(GetUserMenuContextQuery(telegram_id=TELEGRAM_ID))

    assert [item.action_id for item in result.items] == [
        "administrator.home",
        "administrator.scan_qr",
        "administrator.confirm_attendance",
        "administrator.schedule",
        "administrator.activate_subscription",
        "administrator.create_athlete",
        "administrator.link_athlete_account",
        "administrator.assign_trainer",
        "administrator.manage_users",
        "trainer.home",
        "trainer.schedule",
        "athlete.home",
        "athlete.my_qr",
        "athlete.schedule",
        "athlete.my_subscription",
    ]


async def test_owner_and_administrator_do_not_duplicate_admin_actions() -> None:
    interactor, _, _ = build_interactor(
        role_codes=(
            SystemRoleCode.OWNER,
            SystemRoleCode.ADMINISTRATOR,
        )
    )

    result = await interactor(GetUserMenuContextQuery(telegram_id=TELEGRAM_ID))

    assert [item.action_id for item in result.items] == [
        "owner.home",
        "administrator.scan_qr",
        "administrator.confirm_attendance",
        "administrator.schedule",
        "administrator.activate_subscription",
        "administrator.create_athlete",
        "administrator.link_athlete_account",
        "administrator.assign_trainer",
        "administrator.manage_users",
        "administrator.home",
    ]


async def test_user_without_roles_is_controlled_failure() -> None:
    interactor, _, roles = build_interactor()

    with pytest.raises(UserHasNoRolesError):
        await interactor(GetUserMenuContextQuery(telegram_id=TELEGRAM_ID))

    assert roles.requested_user_ids == [101]


async def test_unknown_user_is_controlled_failure() -> None:
    users = FakeUserRepository(None)
    roles = FakeRoleRepository((SystemRoleCode.ATHLETE,))
    interactor = GetUserMenuContextInteractor(
        user_repository=users,
        role_repository=roles,
        scanner_webapp_url=SCANNER_URL,
    )

    with pytest.raises(UserNotFoundError):
        await interactor(GetUserMenuContextQuery(telegram_id=TELEGRAM_ID))

    assert users.requested_telegram_ids == [TELEGRAM_ID]
    assert roles.requested_user_ids == []
