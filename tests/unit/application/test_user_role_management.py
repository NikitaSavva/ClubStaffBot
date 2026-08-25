from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from application.identity import (
    AssignUserRoleCommand,
    AssignUserRoleInteractor,
    AssignUserRoleResult,
    BotUserSummary,
    RemoveUserRoleCommand,
    RemoveUserRoleInteractor,
    RemoveUserRoleResult,
    SearchBotUsersInteractor,
    SearchBotUsersQuery,
    SearchBotUsersResult,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    LastUserRoleRemovalForbiddenError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import Role, SystemRoleCode, User

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ACTOR_TELEGRAM_ID = 123456
ACTOR_USER_ID = 101
TARGET_USER_ID = 202


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
    def __init__(self, users: tuple[User, ...]) -> None:
        self.by_id = {
            user.id: user for user in users if user.id is not None
        }
        self.by_telegram_id = {user.telegram_id: user for user in users}
        self.requested_user_ids: list[int] = []
        self.locked_user_ids: list[int] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self.by_telegram_id.get(telegram_id)

    async def get_by_id(self, user_id: int) -> User | None:
        self.requested_user_ids.append(user_id)
        return self.by_id.get(user_id)

    async def get_by_id_for_update(self, user_id: int) -> User | None:
        self.locked_user_ids.append(user_id)
        return self.by_id.get(user_id)


class FakeRoleRepository:
    def __init__(
        self,
        *,
        active_codes: dict[int, tuple[SystemRoleCode, ...]],
        roles: dict[SystemRoleCode, Role] | None = None,
        assign_result: bool = True,
        remove_result: bool = True,
    ) -> None:
        self.active_codes = active_codes
        self.roles = roles or system_roles()
        self.assign_result = assign_result
        self.remove_result = remove_result
        self.assignments: list[dict[str, object]] = []
        self.removals: list[dict[str, int]] = []

    async def get_by_code(self, code: SystemRoleCode) -> Role | None:
        return self.roles.get(code)

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.active_codes.get(user_id, ())

    async def is_assigned(self, *, user_id: int, role_id: int) -> bool:
        role = next(
            (candidate for candidate in self.roles.values() if candidate.id == role_id),
            None,
        )
        return role is not None and role.code in self.active_codes.get(
            user_id, ()
        )

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
            role = next(
                role for role in self.roles.values() if role.id == role_id
            )
            self.active_codes[user_id] = (
                *self.active_codes.get(user_id, ()),
                role.code,
            )
        return self.assign_result

    async def remove_from_user(
        self,
        *,
        user_id: int,
        role_id: int,
    ) -> bool:
        self.removals.append({"user_id": user_id, "role_id": role_id})
        if self.remove_result:
            role = next(
                role for role in self.roles.values() if role.id == role_id
            )
            self.active_codes[user_id] = tuple(
                code
                for code in self.active_codes.get(user_id, ())
                if code is not role.code
            )
        return self.remove_result


class FakeBotUserReader:
    def __init__(self, users: tuple[BotUserSummary, ...]) -> None:
        self.users = users
        self.queries: list[str] = []

    async def search(self, query: str) -> tuple[BotUserSummary, ...]:
        self.queries.append(query)
        return self.users


class FakeAuditLogRepository:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
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
        if self.error is not None:
            raise self.error
        self.records.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
            }
        )


def user(
    *,
    user_id: int,
    telegram_id: int,
    first_name: str,
) -> User:
    return User(
        id=user_id,
        telegram_id=telegram_id,
        username=first_name.lower(),
        first_name=first_name,
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def actor() -> User:
    return user(
        user_id=ACTOR_USER_ID,
        telegram_id=ACTOR_TELEGRAM_ID,
        first_name="Admin",
    )


def target() -> User:
    return user(
        user_id=TARGET_USER_ID,
        telegram_id=654321,
        first_name="Target",
    )


def system_roles() -> dict[SystemRoleCode, Role]:
    return {
        code: Role(
            id=index,
            code=code,
            is_system=True,
            is_active=True,
        )
        for index, code in enumerate(SystemRoleCode, start=1)
    }


def target_summary(
    role_codes: tuple[SystemRoleCode, ...] = (SystemRoleCode.ATHLETE,),
) -> BotUserSummary:
    return BotUserSummary(
        user_id=TARGET_USER_ID,
        first_name="Target",
        last_name="User",
        username="target",
        role_codes=role_codes,
    )


async def test_administrator_searches_users_and_receives_application_dto() -> None:
    users = FakeUserRepository((actor(),))
    roles = FakeRoleRepository(
        active_codes={ACTOR_USER_ID: (SystemRoleCode.ADMINISTRATOR,)}
    )
    reader = FakeBotUserReader((target_summary(),))
    interactor = SearchBotUsersInteractor(users, roles, reader)

    result = await interactor(
        SearchBotUsersQuery(
            actor_telegram_id=ACTOR_TELEGRAM_ID,
            query="  @target  ",
        )
    )

    assert result == SearchBotUsersResult(
        users=(target_summary(),),
        assignable_role_codes=tuple(SystemRoleCode),
    )
    assert type(result) is SearchBotUsersResult
    assert all(type(item) is BotUserSummary for item in result.users)
    assert reader.queries == ["target"]


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_search_users(
    role_code: SystemRoleCode,
) -> None:
    users = FakeUserRepository((actor(),))
    roles = FakeRoleRepository(
        active_codes={ACTOR_USER_ID: (role_code,)}
    )
    reader = FakeBotUserReader((target_summary(),))
    interactor = SearchBotUsersInteractor(users, roles, reader)

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=ACTOR_TELEGRAM_ID,
                query="target",
            )
        )

    assert reader.queries == []


def build_assign_interactor(
    *,
    actor_role_codes: tuple[SystemRoleCode, ...] = (
        SystemRoleCode.ADMINISTRATOR,
    ),
    target_role_codes: tuple[SystemRoleCode, ...] = (
        SystemRoleCode.ATHLETE,
    ),
    include_target: bool = True,
    roles_by_code: dict[SystemRoleCode, Role] | None = None,
    assign_result: bool = True,
    audit_error: BaseException | None = None,
) -> tuple[
    AssignUserRoleInteractor,
    FakeUserRepository,
    FakeRoleRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    persisted_users = (actor(), target()) if include_target else (actor(),)
    users = FakeUserRepository(persisted_users)
    roles = FakeRoleRepository(
        active_codes={
            ACTOR_USER_ID: actor_role_codes,
            TARGET_USER_ID: target_role_codes,
        },
        roles=roles_by_code,
        assign_result=assign_result,
    )
    audit = FakeAuditLogRepository(audit_error)
    uow = FakeUnitOfWork()
    return (
        AssignUserRoleInteractor(
            user_repository=users,
            role_repository=roles,
            audit_log_repository=audit,
            unit_of_work=uow,
            clock=FrozenClock(),
        ),
        users,
        roles,
        audit,
        uow,
    )


def assign_trainer_command() -> AssignUserRoleCommand:
    return AssignUserRoleCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        target_user_id=TARGET_USER_ID,
        role_code=SystemRoleCode.TRAINER,
    )


async def test_administrator_assigns_additional_role_and_audit_atomically() -> None:
    interactor, users, roles, audit, uow = build_assign_interactor()

    result = await interactor(assign_trainer_command())

    assert result == AssignUserRoleResult(
        target_user_id=TARGET_USER_ID,
        role_code=SystemRoleCode.TRAINER,
        role_was_assigned=True,
        current_role_codes=(
            SystemRoleCode.ATHLETE,
            SystemRoleCode.TRAINER,
        ),
    )
    assert users.requested_user_ids == [TARGET_USER_ID]
    assert roles.assignments == [
        {
            "user_id": TARGET_USER_ID,
            "role_id": system_roles()[SystemRoleCode.TRAINER].id,
            "assigned_by_user_id": ACTOR_USER_ID,
            "assigned_at": NOW,
        }
    ]
    assert audit.records == [
        {
            "actor_user_id": ACTOR_USER_ID,
            "action": "ROLE_ASSIGNED",
            "entity_type": "USER",
            "entity_id": TARGET_USER_ID,
            "payload": {"role_code": "TRAINER"},
        }
    ]
    assert uow.enter_count == 1
    assert uow.commit_count == 1
    assert uow.exit_exception is None


@pytest.mark.parametrize("role_code", tuple(SystemRoleCode))
async def test_administrator_can_assign_each_system_role(
    role_code: SystemRoleCode,
) -> None:
    interactor, _, _, audit, uow = build_assign_interactor(
        target_role_codes=()
    )

    result = await interactor(
        AssignUserRoleCommand(
            actor_telegram_id=ACTOR_TELEGRAM_ID,
            target_user_id=TARGET_USER_ID,
            role_code=role_code,
        )
    )

    assert result.role_was_assigned
    assert result.role_code is role_code
    assert result.current_role_codes == (role_code,)
    assert audit.records[0]["payload"] == {"role_code": role_code.value}
    assert uow.commit_count == 1


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_assign_role(
    role_code: SystemRoleCode,
) -> None:
    interactor, _, roles, audit, uow = build_assign_interactor(
        actor_role_codes=(role_code,)
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(assign_trainer_command())

    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_target_user_must_exist() -> None:
    interactor, _, roles, audit, uow = build_assign_interactor(
        include_target=False
    )

    with pytest.raises(UserNotFoundError):
        await interactor(assign_trainer_command())

    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


@pytest.mark.parametrize(
    "configured_role",
    [
        None,
        Role(
            id=2,
            code=SystemRoleCode.TRAINER,
            is_system=False,
            is_active=True,
        ),
        Role(
            id=2,
            code=SystemRoleCode.TRAINER,
            is_system=True,
            is_active=False,
        ),
    ],
)
async def test_role_must_be_active_system_configuration(
    configured_role: Role | None,
) -> None:
    configured_roles = system_roles()
    if configured_role is None:
        configured_roles.pop(SystemRoleCode.TRAINER)
    else:
        configured_roles[SystemRoleCode.TRAINER] = configured_role
    interactor, _, roles, audit, uow = build_assign_interactor(
        roles_by_code=configured_roles
    )

    with pytest.raises(RequiredSystemRoleMissingError):
        await interactor(assign_trainer_command())

    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_repeated_assignment_is_idempotent_without_audit_or_commit() -> None:
    interactor, _, roles, audit, uow = build_assign_interactor(
        target_role_codes=(
            SystemRoleCode.ATHLETE,
            SystemRoleCode.TRAINER,
        )
    )

    result = await interactor(assign_trainer_command())

    assert not result.role_was_assigned
    assert result.current_role_codes == (
        SystemRoleCode.ATHLETE,
        SystemRoleCode.TRAINER,
    )
    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_concurrent_duplicate_outcome_is_idempotent() -> None:
    interactor, _, roles, audit, uow = build_assign_interactor(
        assign_result=False
    )

    result = await interactor(assign_trainer_command())

    assert not result.role_was_assigned
    assert len(roles.assignments) == 1
    assert audit.records == []
    assert uow.commit_count == 0


async def test_audit_failure_prevents_commit() -> None:
    interactor, _, roles, audit, uow = build_assign_interactor(
        audit_error=RuntimeError("audit persistence failed")
    )

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        await interactor(assign_trainer_command())

    assert len(roles.assignments) == 1
    assert audit.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is RuntimeError


def build_remove_interactor(
    *,
    actor_role_codes: tuple[SystemRoleCode, ...] = (
        SystemRoleCode.ADMINISTRATOR,
    ),
    target_role_codes: tuple[SystemRoleCode, ...] = (
        SystemRoleCode.ATHLETE,
        SystemRoleCode.TRAINER,
    ),
    include_target: bool = True,
    roles_by_code: dict[SystemRoleCode, Role] | None = None,
    remove_result: bool = True,
    audit_error: BaseException | None = None,
) -> tuple[
    RemoveUserRoleInteractor,
    FakeUserRepository,
    FakeRoleRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    persisted_users = (actor(), target()) if include_target else (actor(),)
    users = FakeUserRepository(persisted_users)
    roles = FakeRoleRepository(
        active_codes={
            ACTOR_USER_ID: actor_role_codes,
            TARGET_USER_ID: target_role_codes,
        },
        roles=roles_by_code,
        remove_result=remove_result,
    )
    audit = FakeAuditLogRepository(audit_error)
    uow = FakeUnitOfWork()
    return (
        RemoveUserRoleInteractor(
            user_repository=users,
            role_repository=roles,
            audit_log_repository=audit,
            unit_of_work=uow,
        ),
        users,
        roles,
        audit,
        uow,
    )


def remove_trainer_command() -> RemoveUserRoleCommand:
    return RemoveUserRoleCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        target_user_id=TARGET_USER_ID,
        role_code=SystemRoleCode.TRAINER,
    )


async def test_administrator_removes_only_selected_role_with_audit() -> None:
    interactor, users, roles, audit, uow = build_remove_interactor(
        target_role_codes=tuple(SystemRoleCode)
    )

    result = await interactor(remove_trainer_command())

    assert result == RemoveUserRoleResult(
        target_user_id=TARGET_USER_ID,
        role_code=SystemRoleCode.TRAINER,
        role_was_removed=True,
        current_role_codes=(
            SystemRoleCode.ATHLETE,
            SystemRoleCode.ADMINISTRATOR,
        ),
        target_user=target_summary(
            (
                SystemRoleCode.ATHLETE,
                SystemRoleCode.ADMINISTRATOR,
            )
        ),
    )
    assert users.locked_user_ids == [TARGET_USER_ID]
    assert roles.removals == [
        {
            "user_id": TARGET_USER_ID,
            "role_id": system_roles()[SystemRoleCode.TRAINER].id,
        }
    ]
    assert audit.records == [
        {
            "actor_user_id": ACTOR_USER_ID,
            "action": "ROLE_REMOVED",
            "entity_type": "USER",
            "entity_id": TARGET_USER_ID,
            "payload": {"role_code": "TRAINER"},
        }
    ]
    assert uow.enter_count == 1
    assert uow.commit_count == 1
    assert uow.exit_exception is None


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_remove_role(
    role_code: SystemRoleCode,
) -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        actor_role_codes=(role_code,)
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(remove_trainer_command())

    assert roles.removals == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_last_active_system_role_cannot_be_removed() -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        target_role_codes=(SystemRoleCode.TRAINER,)
    )

    with pytest.raises(LastUserRoleRemovalForbiddenError):
        await interactor(remove_trainer_command())

    assert roles.removals == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_absent_role_is_controlled_idempotent_outcome() -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        target_role_codes=(SystemRoleCode.ATHLETE,)
    )

    result = await interactor(remove_trainer_command())

    assert result == RemoveUserRoleResult(
        target_user_id=TARGET_USER_ID,
        role_code=SystemRoleCode.TRAINER,
        role_was_removed=False,
        current_role_codes=(SystemRoleCode.ATHLETE,),
        target_user=target_summary(),
    )
    assert roles.removals == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_remove_role_target_must_exist() -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        include_target=False
    )

    with pytest.raises(UserNotFoundError):
        await interactor(remove_trainer_command())

    assert roles.removals == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_concurrent_absent_removal_has_no_audit_or_commit() -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        remove_result=False
    )

    result = await interactor(remove_trainer_command())

    assert not result.role_was_removed
    assert roles.removals == [
        {
            "user_id": TARGET_USER_ID,
            "role_id": system_roles()[SystemRoleCode.TRAINER].id,
        }
    ]
    assert audit.records == []
    assert uow.commit_count == 0


async def test_remove_role_audit_failure_prevents_commit() -> None:
    interactor, _, roles, audit, uow = build_remove_interactor(
        audit_error=RuntimeError("audit persistence failed")
    )

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        await interactor(remove_trainer_command())

    assert len(roles.removals) == 1
    assert audit.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is RuntimeError
