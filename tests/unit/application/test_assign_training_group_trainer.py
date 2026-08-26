from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from application.club import (
    AssignTrainingGroupTrainerCommand,
    AssignTrainingGroupTrainerInteractor,
    AssignTrainingGroupTrainerResult,
)
from application.club.errors import (
    TargetUserIsNotTrainerError,
    TrainingGroupNotFoundError,
    TrainingGroupTrainerAlreadyAssignedError,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
from domain.club import TrainingGroup
from domain.identity import SystemRoleCode, User

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
ACTOR_TELEGRAM_ID = 100_001
ACTOR_USER_ID = 1
TRAINING_GROUP_ID = 10
TRAINER_USER_ID = 20
OTHER_TRAINER_USER_ID = 21


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commit_count = 0
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self) -> Self:
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

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self.by_telegram_id.get(telegram_id)

    async def get_by_id(self, user_id: int) -> User | None:
        return self.by_id.get(user_id)


class FakeRoleRepository:
    def __init__(
        self,
        role_codes: dict[int, tuple[SystemRoleCode, ...]],
    ) -> None:
        self.role_codes = role_codes

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.role_codes.get(user_id, ())


class FakeTrainingGroupRepository:
    def __init__(
        self,
        group: TrainingGroup | None,
        *,
        assign_result: bool = True,
    ) -> None:
        self.group = group
        self.assign_result = assign_result
        self.locked_ids: list[int] = []
        self.assignments: list[tuple[int, int]] = []

    async def get_by_id_for_update(
        self,
        training_group_id: int,
    ) -> TrainingGroup | None:
        self.locked_ids.append(training_group_id)
        return self.group

    async def assign_trainer(
        self,
        *,
        training_group_id: int,
        trainer_user_id: int,
    ) -> bool:
        self.assignments.append((training_group_id, trainer_user_id))
        return self.assign_result


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


def user(user_id: int, telegram_id: int) -> User:
    return User(
        id=user_id,
        telegram_id=telegram_id,
        username=f"user{user_id}",
        first_name=f"User{user_id}",
        last_name="Example",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def build_interactor(
    *,
    actor_role: SystemRoleCode = SystemRoleCode.ADMINISTRATOR,
    target_roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.TRAINER,),
    group: TrainingGroup | None = None,
    include_group: bool = True,
    include_target: bool = True,
    assign_result: bool = True,
) -> tuple[
    AssignTrainingGroupTrainerInteractor,
    FakeTrainingGroupRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    actor = user(ACTOR_USER_ID, ACTOR_TELEGRAM_ID)
    trainer = user(TRAINER_USER_ID, 100_020)
    users = FakeUserRepository(
        (actor, trainer) if include_target else (actor,)
    )
    roles = FakeRoleRepository(
        {
            ACTOR_USER_ID: (actor_role,),
            TRAINER_USER_ID: target_roles,
        }
    )
    groups = FakeTrainingGroupRepository(
        group
        or (
            TrainingGroup(id=TRAINING_GROUP_ID, trainer_id=None)
            if include_group
            else None
        ),
        assign_result=assign_result,
    )
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    return (
        AssignTrainingGroupTrainerInteractor(
            user_repository=users,
            role_repository=roles,
            training_group_repository=groups,
            audit_log_repository=audit,
            unit_of_work=uow,
        ),
        groups,
        audit,
        uow,
    )


def command(
    trainer_user_id: int = TRAINER_USER_ID,
) -> AssignTrainingGroupTrainerCommand:
    return AssignTrainingGroupTrainerCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        training_group_id=TRAINING_GROUP_ID,
        trainer_user_id=trainer_user_id,
    )


@pytest.mark.parametrize(
    "actor_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_actor_assigns_trainer_atomically(
    actor_role: SystemRoleCode,
) -> None:
    interactor, groups, audit, uow = build_interactor(
        actor_role=actor_role
    )

    result = await interactor(command())

    assert result == AssignTrainingGroupTrainerResult(
        training_group_id=TRAINING_GROUP_ID,
        trainer_user_id=TRAINER_USER_ID,
    )
    assert groups.locked_ids == [TRAINING_GROUP_ID]
    assert groups.assignments == [(TRAINING_GROUP_ID, TRAINER_USER_ID)]
    assert audit.records == [
        {
            "actor_user_id": ACTOR_USER_ID,
            "action": "TRAINER_ASSIGNED",
            "entity_type": "TRAINING_GROUP",
            "entity_id": TRAINING_GROUP_ID,
            "payload": {"trainer_user_id": TRAINER_USER_ID},
        }
    ]
    assert uow.commit_count == 1
    assert uow.exit_exception is None


@pytest.mark.parametrize(
    "actor_role",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrative_actor_is_forbidden(
    actor_role: SystemRoleCode,
) -> None:
    interactor, groups, audit, uow = build_interactor(
        actor_role=actor_role
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(command())

    assert groups.locked_ids == []
    assert groups.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_target_user_must_have_trainer_among_active_roles() -> None:
    interactor, groups, audit, uow = build_interactor(
        target_roles=(
            SystemRoleCode.ATHLETE,
            SystemRoleCode.ADMINISTRATOR,
        )
    )

    with pytest.raises(TargetUserIsNotTrainerError):
        await interactor(command())

    assert groups.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


@pytest.mark.parametrize(
    "assigned_trainer_id, requested_trainer_id",
    [
        (OTHER_TRAINER_USER_ID, TRAINER_USER_ID),
        (TRAINER_USER_ID, TRAINER_USER_ID),
    ],
)
async def test_assigned_trainer_cannot_be_replaced_or_repeated(
    assigned_trainer_id: int,
    requested_trainer_id: int,
) -> None:
    interactor, groups, audit, uow = build_interactor(
        group=TrainingGroup(
            id=TRAINING_GROUP_ID,
            trainer_id=assigned_trainer_id,
        )
    )

    with pytest.raises(TrainingGroupTrainerAlreadyAssignedError):
        await interactor(command(requested_trainer_id))

    assert groups.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_unknown_training_group_is_controlled_not_found() -> None:
    interactor, groups, audit, uow = build_interactor(include_group=False)

    with pytest.raises(TrainingGroupNotFoundError):
        await interactor(command())

    assert groups.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_unknown_trainer_user_is_controlled_not_found() -> None:
    interactor, groups, audit, uow = build_interactor(
        include_target=False
    )

    with pytest.raises(UserNotFoundError):
        await interactor(command())

    assert groups.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_conditional_update_conflict_does_not_audit_or_commit() -> None:
    interactor, groups, audit, uow = build_interactor(
        assign_result=False
    )

    with pytest.raises(TrainingGroupTrainerAlreadyAssignedError):
        await interactor(command())

    assert groups.assignments == [(TRAINING_GROUP_ID, TRAINER_USER_ID)]
    assert audit.records == []
    assert uow.commit_count == 0
