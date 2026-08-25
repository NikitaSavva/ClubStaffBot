from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest

from application.identity import (
    LinkAthleteAccountResult,
    RegisterBotUserCommand,
    RegisterBotUserInteractor,
)
from application.identity.errors import (
    InvalidBotInviteError,
    RequiredSystemRoleMissingError,
    UserAlreadyRegisteredError,
)
from domain.identity import (
    Athlete,
    BotInvite,
    BotInvitePurpose,
    Role,
    SystemRoleCode,
    User,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeTokenHasher:
    def hash(self, raw_token: str) -> str:
        return f"hashed:{raw_token}"


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.entered = False
        self.commit_count = 0
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self) -> Self:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_exception = exc_type

    async def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, existing_user: User | None = None) -> None:
        self.existing_user = existing_user
        self.added: list[User] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if (
            self.existing_user is not None
            and self.existing_user.telegram_id == telegram_id
        ):
            return self.existing_user
        return None

    async def add(self, user: User) -> int:
        self.added.append(user)
        return 101


class FakeAthleteRepository:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.added: list[Athlete] = []

    async def add(self, athlete: Athlete) -> int:
        if self.error is not None:
            raise self.error
        self.added.append(athlete)
        return 201


class FakeRoleRepository:
    def __init__(self, role: Role | None) -> None:
        self.role = role
        self.assignments: list[dict[str, object]] = []

    async def get_by_code(self, code: SystemRoleCode) -> Role | None:
        if self.role is not None and self.role.code == code:
            return self.role
        return None

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> None:
        self.assignments.append(
            {
                "user_id": user_id,
                "role_id": role_id,
                "assigned_by_user_id": assigned_by_user_id,
                "assigned_at": assigned_at,
            }
        )


class FakeBotInviteRepository:
    def __init__(self, invite: BotInvite | None) -> None:
        self.invite = invite
        self.requested_hashes: list[str] = []

    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None:
        self.requested_hashes.append(token_hash)
        if self.invite is not None and self.invite.token_hash == token_hash:
            return self.invite
        return None


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
    ) -> None:
        self.records.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )


class FakeLinkAthleteAccountInteractor:
    def __init__(self, result: object | None = None) -> None:
        self.result = result

    async def __call__(self, command: object) -> object:
        del command
        if self.result is None:
            raise AssertionError("Reception registration must not use link flow")
        return self.result


def active_invite(**overrides: object) -> BotInvite:
    values: dict[str, object] = {
        "id": 1,
        "token_hash": "hashed:raw-token",
        "purpose": BotInvitePurpose.REGISTRATION,
        "athlete_id": None,
        "is_active": True,
        "expires_at": None,
        "revoked_at": None,
        "consumed_at": None,
    }
    values.update(overrides)
    return BotInvite(**values)  # type: ignore[arg-type]


def athlete_role(**overrides: object) -> Role:
    values: dict[str, object] = {
        "id": 7,
        "code": SystemRoleCode.ATHLETE,
        "is_system": True,
        "is_active": True,
    }
    values.update(overrides)
    return Role(**values)  # type: ignore[arg-type]


def existing_user() -> User:
    return User(
        id=99,
        telegram_id=123456,
        username="existing",
        first_name="Existing",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def command() -> RegisterBotUserCommand:
    return RegisterBotUserCommand(
        telegram_id=123456,
        username="new_user",
        first_name="New",
        last_name=None,
        invite_token="raw-token",
    )


def build_interactor(
    *,
    invite: BotInvite | None = None,
    role: Role | None = None,
    user: User | None = None,
    athlete_error: BaseException | None = None,
    link_result: object | None = None,
) -> tuple[
    RegisterBotUserInteractor,
    FakeUserRepository,
    FakeAthleteRepository,
    FakeRoleRepository,
    FakeBotInviteRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    users = FakeUserRepository(user)
    athletes = FakeAthleteRepository(athlete_error)
    roles = FakeRoleRepository(role if role is not None else athlete_role())
    invites = FakeBotInviteRepository(
        invite if invite is not None else active_invite()
    )
    audit_log = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    interactor = RegisterBotUserInteractor(
        user_repository=users,
        athlete_repository=athletes,
        role_repository=roles,
        bot_invite_repository=invites,
        audit_log_repository=audit_log,
        unit_of_work=uow,
        clock=FrozenClock(),
        token_hasher=FakeTokenHasher(),
        link_athlete_account_interactor=FakeLinkAthleteAccountInteractor(
            link_result
        ),  # type: ignore[arg-type]
    )
    return interactor, users, athletes, roles, invites, audit_log, uow


async def test_successful_registration_assigns_athlete_role_and_commits() -> None:
    interactor, users, athletes, roles, invites, audit_log, uow = (
        build_interactor()
    )

    result = await interactor(command())

    assert result.user_id == 101
    assert result.telegram_id == 123456
    assert result.role_code is SystemRoleCode.ATHLETE
    assert result.registered_at == NOW
    assert invites.requested_hashes == ["hashed:raw-token"]
    assert users.added == [
        User(
            id=None,
            telegram_id=123456,
            username="new_user",
            first_name="New",
            last_name="",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
    ]
    assert roles.assignments == [
        {
            "user_id": 101,
            "role_id": 7,
            "assigned_by_user_id": None,
            "assigned_at": NOW,
        }
    ]
    assert len(athletes.added) == 1
    athlete = athletes.added[0]
    assert athlete.id is None
    assert athlete.athlete_public_id.version == 4
    assert athlete.user_id == 101
    assert athlete.first_name == "New"
    assert athlete.last_name is None
    assert athlete.birth_date is None
    assert athlete.phone is None
    assert athlete.is_active
    assert audit_log.records == [
        {
            "actor_user_id": 101,
            "action": "USER_REGISTERED",
            "entity_type": "USER",
            "entity_id": 101,
        }
    ]
    assert uow.entered
    assert uow.commit_count == 1
    assert uow.exit_exception is None


@pytest.mark.parametrize(
    "invite",
    [
        active_invite(is_active=False),
        active_invite(expires_at=NOW),
        active_invite(expires_at=NOW - timedelta(seconds=1)),
        active_invite(revoked_at=NOW),
    ],
)
async def test_unavailable_invite_does_not_commit(invite: BotInvite) -> None:
    interactor, users, athletes, roles, _, audit_log, uow = build_interactor(
        invite=invite
    )

    with pytest.raises(InvalidBotInviteError):
        await interactor(command())

    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert audit_log.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is InvalidBotInviteError


async def test_unknown_invite_does_not_commit() -> None:
    interactor, users, athletes, roles, invites, audit_log, uow = (
        build_interactor()
    )
    invites.invite = None

    with pytest.raises(InvalidBotInviteError):
        await interactor(command())

    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert audit_log.records == []
    assert uow.commit_count == 0


async def test_existing_telegram_user_is_controlled_failure() -> None:
    interactor, users, athletes, roles, invites, audit_log, uow = build_interactor(
        user=existing_user()
    )

    with pytest.raises(UserAlreadyRegisteredError):
        await interactor(command())

    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert invites.requested_hashes == []
    assert audit_log.records == []
    assert uow.commit_count == 0


@pytest.mark.parametrize(
    "role",
    [
        athlete_role(is_active=False),
        athlete_role(is_system=False),
    ],
)
async def test_misconfigured_athlete_role_does_not_commit(role: Role) -> None:
    interactor, users, athletes, roles, _, audit_log, uow = build_interactor(
        role=role
    )

    with pytest.raises(RequiredSystemRoleMissingError):
        await interactor(command())

    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert audit_log.records == []
    assert uow.commit_count == 0


async def test_missing_athlete_role_does_not_commit() -> None:
    interactor, users, athletes, roles, _, audit_log, uow = build_interactor()
    roles.role = None

    with pytest.raises(RequiredSystemRoleMissingError):
        await interactor(command())

    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert audit_log.records == []
    assert uow.commit_count == 0


async def test_athlete_failure_does_not_audit_or_commit() -> None:
    interactor, _, athletes, roles, _, audit_log, uow = build_interactor(
        athlete_error=RuntimeError("athlete persistence failed")
    )

    with pytest.raises(RuntimeError, match="athlete persistence failed"):
        await interactor(command())

    assert athletes.added == []
    assert len(roles.assignments) == 1
    assert audit_log.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is RuntimeError


async def test_account_link_invite_is_routed_to_link_interactor() -> None:
    link_result = LinkAthleteAccountResult(
        user_id=101,
        athlete_id=201,
        telegram_id=123456,
        role_code=SystemRoleCode.ATHLETE,
        linked_at=NOW,
    )
    interactor, users, athletes, roles, _, audit_log, uow = build_interactor(
        invite=active_invite(
            purpose=BotInvitePurpose.ATHLETE_LINK,
            athlete_id=201,
        ),
        link_result=link_result,
    )

    result = await interactor(command())

    assert result is link_result
    assert users.added == []
    assert athletes.added == []
    assert roles.assignments == []
    assert audit_log.records == []
    assert uow.commit_count == 0
