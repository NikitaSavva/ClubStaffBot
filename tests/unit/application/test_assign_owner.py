from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from application.identity import AssignOwnerCommand, AssignOwnerInteractor
from application.identity.errors import (
    OwnerAlreadyAssignedError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import Role, SystemRoleCode, User

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
TARGET_TELEGRAM_ID = 111_222_333
TARGET_USER_ID = 101
OTHER_USER_ID = 202


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.enter_count = 0
        self.commit_count = 0
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self) -> Self:
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        self.exit_exception = exc_type

    async def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, target: User | None) -> None:
        self.target = target
        self.requested_telegram_ids: list[int] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        self.requested_telegram_ids.append(telegram_id)
        return self.target


class FakeRoleRepository:
    def __init__(
        self,
        *,
        owner_role: Role | None,
        assigned_user_id: int | None = None,
        assign_result: bool = True,
    ) -> None:
        self.owner_role = owner_role
        self.assigned_user_id = assigned_user_id
        self.assign_result = assign_result
        self.locked_codes: list[SystemRoleCode] = []
        self.assignments: list[dict[str, object]] = []

    async def get_by_code_for_update(
        self,
        code: SystemRoleCode,
    ) -> Role | None:
        self.locked_codes.append(code)
        return self.owner_role

    async def get_assigned_user_id(self, role_id: int) -> int | None:
        assert self.owner_role is not None
        assert role_id == self.owner_role.id
        return self.assigned_user_id

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> bool:
        self.assignments.append(
            {
                "user_id": user_id,
                "role_id": role_id,
                "assigned_by_user_id": assigned_by_user_id,
                "assigned_at": assigned_at,
            }
        )
        if self.assign_result:
            self.assigned_user_id = user_id
        return self.assign_result

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        if user_id == self.assigned_user_id:
            return (SystemRoleCode.ATHLETE, SystemRoleCode.OWNER)
        return (SystemRoleCode.ATHLETE,)


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.records.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
            }
        )


def target_user() -> User:
    return User(
        id=TARGET_USER_ID,
        telegram_id=TARGET_TELEGRAM_ID,
        username="target",
        first_name="Target",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def owner_role(*, is_system: bool = True, is_active: bool = True) -> Role:
    return Role(
        id=4,
        code=SystemRoleCode.OWNER,
        is_system=is_system,
        is_active=is_active,
    )


def build_interactor(
    *,
    target: User | None = None,
    configured_owner_role: Role | None = None,
    assigned_user_id: int | None = None,
    assign_result: bool = True,
) -> tuple[
    AssignOwnerInteractor,
    FakeUserRepository,
    FakeRoleRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    users = FakeUserRepository(target if target is not None else target_user())
    roles = FakeRoleRepository(
        owner_role=(
            configured_owner_role
            if configured_owner_role is not None
            else owner_role()
        ),
        assigned_user_id=assigned_user_id,
        assign_result=assign_result,
    )
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    return (
        AssignOwnerInteractor(users, roles, audit, uow, FrozenClock()),
        users,
        roles,
        audit,
        uow,
    )


async def test_assigns_initial_owner_with_system_audit_and_single_commit() -> None:
    interactor, users, roles, audit, uow = build_interactor()

    result = await interactor(
        AssignOwnerCommand(telegram_id=TARGET_TELEGRAM_ID)
    )

    assert result.owner_was_assigned
    assert result.target_user_id == TARGET_USER_ID
    assert result.current_role_codes == (
        SystemRoleCode.ATHLETE,
        SystemRoleCode.OWNER,
    )
    assert users.requested_telegram_ids == [TARGET_TELEGRAM_ID]
    assert roles.locked_codes == [SystemRoleCode.OWNER]
    assert roles.assignments == [
        {
            "user_id": TARGET_USER_ID,
            "role_id": 4,
            "assigned_by_user_id": None,
            "assigned_at": NOW,
        }
    ]
    assert audit.records == [
        {
            "actor_user_id": None,
            "action": "OWNER_ASSIGNED",
            "entity_type": "USER",
            "entity_id": TARGET_USER_ID,
            "payload": {
                "role_code": "OWNER",
                "source": "OPERATOR_SCRIPT",
            },
        }
    ]
    assert uow.commit_count == 1


async def test_repeated_assignment_to_same_user_is_noop_without_audit() -> None:
    interactor, _, roles, audit, uow = build_interactor(
        assigned_user_id=TARGET_USER_ID
    )

    result = await interactor(
        AssignOwnerCommand(telegram_id=TARGET_TELEGRAM_ID)
    )

    assert not result.owner_was_assigned
    assert result.current_role_codes == (
        SystemRoleCode.ATHLETE,
        SystemRoleCode.OWNER,
    )
    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_assignment_refuses_automatic_transfer() -> None:
    interactor, _, roles, audit, uow = build_interactor(
        assigned_user_id=OTHER_USER_ID
    )

    with pytest.raises(OwnerAlreadyAssignedError):
        await interactor(AssignOwnerCommand(telegram_id=TARGET_TELEGRAM_ID))

    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_assignment_requires_existing_user() -> None:
    users = FakeUserRepository(None)
    roles = FakeRoleRepository(owner_role=owner_role())
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    interactor = AssignOwnerInteractor(
        users,
        roles,
        audit,
        uow,
        FrozenClock(),
    )

    with pytest.raises(UserNotFoundError):
        await interactor(AssignOwnerCommand(telegram_id=TARGET_TELEGRAM_ID))

    assert roles.locked_codes == []
    assert audit.records == []
    assert uow.commit_count == 0


@pytest.mark.parametrize(
    "configured_owner_role",
    [
        None,
        owner_role(is_system=False),
        owner_role(is_active=False),
    ],
)
async def test_assignment_requires_active_system_owner_role(
    configured_owner_role: Role | None,
) -> None:
    users = FakeUserRepository(target_user())
    roles = FakeRoleRepository(owner_role=configured_owner_role)
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    interactor = AssignOwnerInteractor(
        users,
        roles,
        audit,
        uow,
        FrozenClock(),
    )

    with pytest.raises(RequiredSystemRoleMissingError):
        await interactor(AssignOwnerCommand(telegram_id=TARGET_TELEGRAM_ID))

    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0
