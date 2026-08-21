from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from application.athletes import (
    CreateManualAthleteCommand,
    CreateManualAthleteInteractor,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
)
from domain.identity import (
    Athlete,
    AthleteFirstNameRequiredError,
    SystemRoleCode,
    User,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


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
    def __init__(self, user: User) -> None:
        self.user = user
        self.added: list[User] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id == self.user.telegram_id:
            return self.user
        return None

    async def add(self, user: User) -> int:
        self.added.append(user)
        return 999


class FakeRoleRepository:
    def __init__(self, role_codes: tuple[SystemRoleCode, ...]) -> None:
        self.role_codes = role_codes
        self.assignments: list[dict[str, object]] = []

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        del user_id
        return self.role_codes

    async def assign_to_user(self, **values: object) -> None:
        self.assignments.append(values)


class FakeAthleteRepository:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.added: list[Athlete] = []

    async def add(self, athlete: Athlete) -> int:
        if self.error is not None:
            raise self.error
        self.added.append(athlete)
        return 201 + len(self.added) - 1


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
    ) -> None:
        if self.error is not None:
            raise self.error
        self.records.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )


def actor() -> User:
    return User(
        id=101,
        telegram_id=123456,
        username="administrator",
        first_name="Admin",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def build_interactor(
    *,
    role_codes: tuple[SystemRoleCode, ...] = (
        SystemRoleCode.ADMINISTRATOR,
    ),
    athlete_error: BaseException | None = None,
    audit_error: BaseException | None = None,
) -> tuple[
    CreateManualAthleteInteractor,
    FakeUserRepository,
    FakeAthleteRepository,
    FakeRoleRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    users = FakeUserRepository(actor())
    athletes = FakeAthleteRepository(athlete_error)
    roles = FakeRoleRepository(role_codes)
    audit = FakeAuditLogRepository(audit_error)
    uow = FakeUnitOfWork()
    return (
        CreateManualAthleteInteractor(users, athletes, roles, audit, uow),
        users,
        athletes,
        roles,
        audit,
        uow,
    )


async def test_administrator_creates_only_unlinked_athlete_and_audit() -> None:
    interactor, users, athletes, roles, audit, uow = build_interactor()

    result = await interactor(
        CreateManualAthleteCommand(
            actor_telegram_id=123456,
            first_name="  Ирина  ",
        )
    )

    assert result.first_name == "Ирина"
    assert len(athletes.added) == 1
    athlete = athletes.added[0]
    assert athlete.user_id is None
    assert athlete.athlete_public_id.version == 4
    assert athlete.first_name == "Ирина"
    assert athlete.last_name is None
    assert athlete.phone is None
    assert users.added == []
    assert roles.assignments == []
    assert audit.records == [
        {
            "actor_user_id": 101,
            "action": "ATHLETE_CREATED_MANUALLY",
            "entity_type": "ATHLETE",
            "entity_id": 201,
        }
    ]
    assert uow.enter_count == 1
    assert uow.commit_count == 1
    assert uow.exit_exception is None


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_create_athlete(
    role_code: SystemRoleCode,
) -> None:
    interactor, users, athletes, roles, audit, uow = build_interactor(
        role_codes=(role_code,)
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=123456,
                first_name="Ирина",
            )
        )

    assert athletes.added == []
    assert users.added == []
    assert roles.assignments == []
    assert audit.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is AdministratorPermissionRequiredError


async def test_blank_name_does_not_create_audit_or_commit() -> None:
    interactor, _, athletes, _, audit, uow = build_interactor()

    with pytest.raises(AthleteFirstNameRequiredError):
        await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=123456,
                first_name="   ",
            )
        )

    assert athletes.added == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_athlete_persistence_failure_does_not_audit_or_commit() -> None:
    interactor, _, athletes, _, audit, uow = build_interactor(
        athlete_error=RuntimeError("athlete persistence failed")
    )

    with pytest.raises(RuntimeError, match="athlete persistence failed"):
        await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=123456,
                first_name="Ирина",
            )
        )

    assert athletes.added == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_audit_failure_does_not_commit() -> None:
    interactor, _, athletes, _, audit, uow = build_interactor(
        audit_error=RuntimeError("audit persistence failed")
    )

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=123456,
                first_name="Ирина",
            )
        )

    assert len(athletes.added) == 1
    assert audit.records == []
    assert uow.commit_count == 0


async def test_equal_names_do_not_trigger_deduplication() -> None:
    interactor, _, athletes, _, audit, uow = build_interactor()
    command = CreateManualAthleteCommand(
        actor_telegram_id=123456,
        first_name="Ирина",
    )

    await interactor(command)
    await interactor(command)

    assert [athlete.first_name for athlete in athletes.added] == [
        "Ирина",
        "Ирина",
    ]
    assert len(audit.records) == 2
    assert uow.commit_count == 2
