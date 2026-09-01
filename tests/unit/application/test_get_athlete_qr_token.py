from datetime import UTC, datetime
from uuid import UUID

import pytest

from application.athlete_qr import (
    GetAthleteQrTokenInteractor,
    GetAthleteQrTokenQuery,
)
from application.identity.errors import (
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
)
from domain.identity import Athlete, SystemRoleCode, User

TELEGRAM_ID = 12345
USER_ID = 10
ATHLETE_PUBLIC_ID = UUID("12345678-1234-4678-9234-567812345678")
NOW = datetime(2026, 9, 1, 10, tzinfo=UTC)


class FakeUserRepository:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id != TELEGRAM_ID:
            return None
        return User(
            id=USER_ID,
            telegram_id=TELEGRAM_ID,
            username="athlete",
            first_name="Иван",
            last_name="Иванов",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )


class FakeRoleRepository:
    def __init__(self, roles: tuple[SystemRoleCode, ...]) -> None:
        self.roles = roles

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.roles if user_id == USER_ID else ()


class FakeAthleteRepository:
    def __init__(self, athlete: Athlete | None) -> None:
        self.athlete = athlete
        self.requested_user_ids: list[int] = []

    async def get_by_user_id(self, user_id: int) -> Athlete | None:
        self.requested_user_ids.append(user_id)
        return self.athlete


class FakeAthleteQrTokenCodec:
    def __init__(self) -> None:
        self.issued_for: list[UUID] = []

    def issue(self, athlete_public_id: UUID) -> str:
        self.issued_for.append(athlete_public_id)
        return "signed-athlete-token"


def linked_athlete() -> Athlete:
    return Athlete(
        id=20,
        athlete_public_id=ATHLETE_PUBLIC_ID,
        user_id=USER_ID,
        first_name="Иван",
        last_name="Иванов",
        birth_date=None,
        phone=None,
        is_active=True,
    )


def make_interactor(
    *,
    roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.ATHLETE,),
    athlete: Athlete | None = None,
) -> tuple[
    GetAthleteQrTokenInteractor,
    FakeAthleteRepository,
    FakeAthleteQrTokenCodec,
]:
    athletes = FakeAthleteRepository(
        linked_athlete() if athlete is None else athlete
    )
    codec = FakeAthleteQrTokenCodec()
    return (
        GetAthleteQrTokenInteractor(
            user_repository=FakeUserRepository(),
            athlete_repository=athletes,
            role_repository=FakeRoleRepository(roles),
            token_codec=codec,
        ),
        athletes,
        codec,
    )


async def test_issues_token_for_linked_athlete_without_subscription() -> None:
    interactor, athletes, codec = make_interactor()

    result = await interactor(
        GetAthleteQrTokenQuery(actor_telegram_id=TELEGRAM_ID)
    )

    assert result.token == "signed-athlete-token"
    assert athletes.requested_user_ids == [USER_ID]
    assert codec.issued_for == [ATHLETE_PUBLIC_ID]


@pytest.mark.parametrize(
    "roles",
    [
        (SystemRoleCode.OWNER, SystemRoleCode.ATHLETE),
        (SystemRoleCode.ADMINISTRATOR, SystemRoleCode.ATHLETE),
        (SystemRoleCode.TRAINER, SystemRoleCode.ATHLETE),
    ],
)
async def test_multi_role_user_with_athlete_role_is_allowed(
    roles: tuple[SystemRoleCode, ...],
) -> None:
    interactor, _, codec = make_interactor(roles=roles)

    await interactor(GetAthleteQrTokenQuery(actor_telegram_id=TELEGRAM_ID))

    assert codec.issued_for == [ATHLETE_PUBLIC_ID]


@pytest.mark.parametrize(
    "role",
    [
        SystemRoleCode.OWNER,
        SystemRoleCode.ADMINISTRATOR,
        SystemRoleCode.TRAINER,
    ],
)
async def test_user_without_athlete_role_is_forbidden(
    role: SystemRoleCode,
) -> None:
    interactor, athletes, codec = make_interactor(roles=(role,))

    with pytest.raises(AthletePermissionRequiredError):
        await interactor(
            GetAthleteQrTokenQuery(actor_telegram_id=TELEGRAM_ID)
        )

    assert not athletes.requested_user_ids
    assert not codec.issued_for


async def test_missing_linked_athlete_is_controlled() -> None:
    interactor, athletes, codec = make_interactor(athlete=None)
    athletes.athlete = None

    with pytest.raises(AthleteProfileNotFoundError):
        await interactor(
            GetAthleteQrTokenQuery(actor_telegram_id=TELEGRAM_ID)
        )

    assert athletes.requested_user_ids == [USER_ID]
    assert not codec.issued_for
