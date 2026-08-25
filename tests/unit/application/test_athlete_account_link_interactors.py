from dataclasses import replace
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Self
from uuid import uuid4

import pytest

from application.identity import (
    CreateAthleteAccountLinkInviteCommand,
    CreateAthleteAccountLinkInviteInteractor,
    LinkAthleteAccountCommand,
    LinkAthleteAccountInteractor,
    ListUnlinkedAthletesInteractor,
    ListUnlinkedAthletesQuery,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteAlreadyLinkedError,
    InvalidBotInviteError,
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

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeTokenHasher:
    def hash(self, raw_token: str) -> str:
        return f"hashed:{raw_token}"


class FakeTokenGenerator:
    def generate(self) -> str:
        return "opaque-raw-token"


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
        self.exit_exception = exc_type

    async def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, users: tuple[User, ...] = ()) -> None:
        self.users = {user.telegram_id: user for user in users}
        self.added: list[User] = []

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self.users.get(telegram_id)

    async def add(self, user: User) -> int:
        self.added.append(user)
        return 501


class FakeAthleteRepository:
    def __init__(self, athletes: tuple[Athlete, ...]) -> None:
        self.athletes = {
            athlete.id: athlete for athlete in athletes if athlete.id is not None
        }
        self.added: list[Athlete] = []
        self.links: list[tuple[int, int]] = []

    async def add(self, athlete: Athlete) -> int:
        self.added.append(athlete)
        return 999

    async def get_by_id_for_update(
        self,
        athlete_id: int,
    ) -> Athlete | None:
        return self.athletes.get(athlete_id)

    async def list_unlinked(self) -> tuple[Athlete, ...]:
        return tuple(
            athlete
            for athlete in self.athletes.values()
            if athlete.user_id is None
        )

    async def link_to_user(self, *, athlete_id: int, user_id: int) -> bool:
        athlete = self.athletes.get(athlete_id)
        if athlete is None or athlete.user_id is not None:
            return False
        self.athletes[athlete_id] = replace(athlete, user_id=user_id)
        self.links.append((athlete_id, user_id))
        return True


class FakeRoleRepository:
    def __init__(
        self,
        *,
        active_codes: tuple[SystemRoleCode, ...] = (),
        athlete_role: Role | None = None,
    ) -> None:
        self.active_codes = active_codes
        self.athlete_role = athlete_role or Role(
            id=7,
            code=SystemRoleCode.ATHLETE,
            is_system=True,
            is_active=True,
        )
        self.assignments: list[dict[str, object]] = []

    async def get_by_code(self, code: SystemRoleCode) -> Role | None:
        if code is SystemRoleCode.ATHLETE:
            return self.athlete_role
        return None

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        del user_id
        return self.active_codes

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
    def __init__(self, invite: BotInvite | None = None) -> None:
        self.invite = invite
        self.added: list[BotInvite] = []
        self.consumed: list[tuple[int, datetime]] = []

    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None:
        if self.invite is not None and self.invite.token_hash == token_hash:
            return self.invite
        return None

    async def get_by_token_hash_for_update(
        self,
        token_hash: str,
    ) -> BotInvite | None:
        return await self.get_by_token_hash(token_hash)

    async def add(self, invite: BotInvite) -> int:
        self.added.append(invite)
        return 601

    async def consume(self, *, invite_id: int, consumed_at: datetime) -> bool:
        self.consumed.append((invite_id, consumed_at))
        return True


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


def user(*, user_id: int = 101, telegram_id: int = 123) -> User:
    return User(
        id=user_id,
        telegram_id=telegram_id,
        username="user",
        first_name="Test",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def athlete(
    *,
    athlete_id: int = 201,
    user_id: int | None = None,
    birth_date: date | None = date(1993, 8, 25),
) -> Athlete:
    return Athlete(
        id=athlete_id,
        athlete_public_id=uuid4(),
        user_id=user_id,
        first_name="Иван",
        last_name="Иванов",
        birth_date=birth_date,
        phone=None,
        is_active=True,
    )


def link_invite(**overrides: object) -> BotInvite:
    values: dict[str, object] = {
        "id": 301,
        "token_hash": "hashed:raw-link-token",
        "purpose": BotInvitePurpose.ATHLETE_LINK,
        "athlete_id": 201,
        "is_active": True,
        "expires_at": None,
        "revoked_at": None,
        "consumed_at": None,
    }
    values.update(overrides)
    return BotInvite(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_actor_lists_only_unlinked_athletes(
    administrative_role: SystemRoleCode,
) -> None:
    users = FakeUserRepository((user(),))
    athletes = FakeAthleteRepository(
        (athlete(), athlete(athlete_id=202, user_id=999))
    )
    roles = FakeRoleRepository(active_codes=(administrative_role,))
    interactor = ListUnlinkedAthletesInteractor(users, athletes, roles)

    result = await interactor(ListUnlinkedAthletesQuery(actor_telegram_id=123))

    assert len(result) == 1
    assert result[0].athlete_id == 201
    assert result[0].full_name == "Иван Иванов"
    assert result[0].birth_date == date(1993, 8, 25)


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_list_unlinked_athletes(
    role_code: SystemRoleCode,
) -> None:
    interactor = ListUnlinkedAthletesInteractor(
        FakeUserRepository((user(),)),
        FakeAthleteRepository((athlete(),)),
        FakeRoleRepository(active_codes=(role_code,)),
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(ListUnlinkedAthletesQuery(actor_telegram_id=123))


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_actor_creates_hashed_invite_and_audit(
    administrative_role: SystemRoleCode,
) -> None:
    users = FakeUserRepository((user(),))
    athletes = FakeAthleteRepository((athlete(),))
    roles = FakeRoleRepository(active_codes=(administrative_role,))
    invites = FakeBotInviteRepository()
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    interactor = CreateAthleteAccountLinkInviteInteractor(
        users,
        athletes,
        roles,
        invites,
        audit,
        uow,
        FakeTokenGenerator(),
        FakeTokenHasher(),
    )

    result = await interactor(
        CreateAthleteAccountLinkInviteCommand(
            actor_telegram_id=123,
            athlete_id=201,
        )
    )

    assert result.raw_token == "opaque-raw-token"
    assert result.invite_id == 601
    assert invites.added == [
        BotInvite(
            id=None,
            token_hash="hashed:opaque-raw-token",
            purpose=BotInvitePurpose.ATHLETE_LINK,
            athlete_id=201,
            is_active=True,
            expires_at=None,
            revoked_at=None,
            consumed_at=None,
        )
    ]
    assert audit.records == [
        {
            "actor_user_id": 101,
            "action": "ATHLETE_ACCOUNT_LINK_INVITE_CREATED",
            "entity_type": "BOT_INVITE",
            "entity_id": 601,
        }
    ]
    assert uow.commit_count == 1


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_create_invite(
    role_code: SystemRoleCode,
) -> None:
    invites = FakeBotInviteRepository()
    uow = FakeUnitOfWork()
    interactor = CreateAthleteAccountLinkInviteInteractor(
        FakeUserRepository((user(),)),
        FakeAthleteRepository((athlete(),)),
        FakeRoleRepository(active_codes=(role_code,)),
        invites,
        FakeAuditLogRepository(),
        uow,
        FakeTokenGenerator(),
        FakeTokenHasher(),
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(
            CreateAthleteAccountLinkInviteCommand(
                actor_telegram_id=123,
                athlete_id=201,
            )
        )

    assert invites.added == []
    assert uow.commit_count == 0


def build_link_interactor(
    *,
    invite: BotInvite | None = None,
    existing_users: tuple[User, ...] = (),
    existing_athlete: Athlete | None = None,
) -> tuple[
    LinkAthleteAccountInteractor,
    FakeUserRepository,
    FakeAthleteRepository,
    FakeRoleRepository,
    FakeBotInviteRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    users = FakeUserRepository(existing_users)
    athletes = FakeAthleteRepository((existing_athlete or athlete(),))
    roles = FakeRoleRepository()
    invites = FakeBotInviteRepository(invite or link_invite())
    audit = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    interactor = LinkAthleteAccountInteractor(
        users,
        athletes,
        roles,
        invites,
        audit,
        uow,
        FrozenClock(),
        FakeTokenHasher(),
    )
    return interactor, users, athletes, roles, invites, audit, uow


def link_command() -> LinkAthleteAccountCommand:
    return LinkAthleteAccountCommand(
        telegram_id=456,
        username="new_athlete",
        first_name="Telegram",
        last_name="User",
        invite_token="raw-link-token",
    )


async def test_link_flow_creates_user_role_and_links_existing_athlete() -> None:
    interactor, users, athletes, roles, invites, audit, uow = (
        build_link_interactor()
    )

    result = await interactor(link_command())

    assert result.user_id == 501
    assert result.athlete_id == 201
    assert result.role_code is SystemRoleCode.ATHLETE
    assert len(users.added) == 1
    assert roles.assignments == [
        {
            "user_id": 501,
            "role_id": 7,
            "assigned_by_user_id": None,
            "assigned_at": NOW,
        }
    ]
    assert athletes.added == []
    assert athletes.links == [(201, 501)]
    assert invites.consumed == [(301, NOW)]
    assert audit.records == [
        {
            "actor_user_id": 501,
            "action": "ATHLETE_ACCOUNT_LINKED",
            "entity_type": "ATHLETE",
            "entity_id": 201,
        }
    ]
    assert uow.commit_count == 1


async def test_existing_telegram_user_is_not_relinked() -> None:
    interactor, users, athletes, roles, invites, audit, uow = (
        build_link_interactor(existing_users=(user(telegram_id=456),))
    )

    with pytest.raises(UserAlreadyRegisteredError):
        await interactor(link_command())

    assert users.added == []
    assert roles.assignments == []
    assert athletes.links == []
    assert invites.consumed == []
    assert audit.records == []
    assert uow.commit_count == 0


@pytest.mark.parametrize(
    "invite",
    [
        link_invite(consumed_at=NOW),
        link_invite(purpose=BotInvitePurpose.REGISTRATION, athlete_id=None),
    ],
)
async def test_unavailable_link_invite_is_controlled_failure(
    invite: BotInvite,
) -> None:
    interactor, users, athletes, roles, invites, audit, uow = (
        build_link_interactor(invite=invite)
    )

    with pytest.raises(InvalidBotInviteError):
        await interactor(link_command())

    assert users.added == []
    assert roles.assignments == []
    assert athletes.links == []
    assert invites.consumed == []
    assert audit.records == []
    assert uow.commit_count == 0


async def test_already_linked_athlete_rolls_back_without_commit() -> None:
    interactor, users, athletes, roles, invites, audit, uow = (
        build_link_interactor(
            existing_athlete=athlete(user_id=999),
        )
    )

    with pytest.raises(AthleteAlreadyLinkedError):
        await interactor(link_command())

    assert len(users.added) == 1
    assert len(roles.assignments) == 1
    assert athletes.links == []
    assert invites.consumed == []
    assert audit.records == []
    assert uow.commit_count == 0
    assert uow.exit_exception is AthleteAlreadyLinkedError
