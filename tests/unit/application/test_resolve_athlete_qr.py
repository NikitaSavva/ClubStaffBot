from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from application.athlete_qr import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
)
from application.scanner import (
    ResolveAthleteQrInteractor,
    ResolveAthleteQrQuery,
)
from domain.identity import Athlete, SystemRoleCode, User

ACTOR_TELEGRAM_ID = 100_200
ACTOR_USER_ID = 10
ATHLETE_PUBLIC_ID = UUID("12345678-1234-4678-9234-567812345678")
ATHLETE_BIRTH_DATE = date(1991, 12, 27)
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


class FakeUserRepository:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id != ACTOR_TELEGRAM_ID:
            return None
        return User(
            id=ACTOR_USER_ID,
            telegram_id=ACTOR_TELEGRAM_ID,
            username="administrator",
            first_name="Admin",
            last_name="User",
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
        return self.roles if user_id == ACTOR_USER_ID else ()


class FakeAthleteRepository:
    def __init__(self, athlete: Athlete | None) -> None:
        self.athlete = athlete
        self.requested_public_ids: list[UUID] = []

    async def get_by_public_id(
        self,
        athlete_public_id: UUID,
    ) -> Athlete | None:
        self.requested_public_ids.append(athlete_public_id)
        return self.athlete


class FakeAthleteQrTokenCodec:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.verified_tokens: list[str] = []

    def verify(self, token: str) -> UUID:
        self.verified_tokens.append(token)
        if self.error is not None:
            raise self.error
        return ATHLETE_PUBLIC_ID


def athlete() -> Athlete:
    return Athlete(
        id=55,
        athlete_public_id=ATHLETE_PUBLIC_ID,
        user_id=None,
        first_name="Иван",
        last_name="Иванов",
        birth_date=ATHLETE_BIRTH_DATE,
        phone=None,
        is_active=True,
    )


def make_interactor(
    *,
    roles: tuple[SystemRoleCode, ...],
    resolved_athlete: Athlete | None = None,
    codec_error: Exception | None = None,
) -> tuple[
    ResolveAthleteQrInteractor,
    FakeAthleteRepository,
    FakeAthleteQrTokenCodec,
]:
    athletes = FakeAthleteRepository(
        athlete() if resolved_athlete is None else resolved_athlete
    )
    codec = FakeAthleteQrTokenCodec(codec_error)
    return (
        ResolveAthleteQrInteractor(
            user_repository=FakeUserRepository(),
            athlete_repository=athletes,
            role_repository=FakeRoleRepository(roles),
            token_codec=codec,
        ),
        athletes,
        codec,
    )


@pytest.mark.parametrize(
    "roles",
    [
        (SystemRoleCode.ADMINISTRATOR,),
        (SystemRoleCode.OWNER,),
        (SystemRoleCode.ADMINISTRATOR, SystemRoleCode.ATHLETE),
        (SystemRoleCode.OWNER, SystemRoleCode.TRAINER),
    ],
)
async def test_administrative_roles_resolve_athlete(
    roles: tuple[SystemRoleCode, ...],
) -> None:
    interactor, athletes, codec = make_interactor(roles=roles)

    result = await interactor(
        ResolveAthleteQrQuery(
            actor_telegram_id=ACTOR_TELEGRAM_ID,
            athlete_qr_token="signed-athlete-token",
        )
    )

    assert result.full_name == "Иван Иванов"
    assert result.birth_date == ATHLETE_BIRTH_DATE
    assert codec.verified_tokens == ["signed-athlete-token"]
    assert athletes.requested_public_ids == [ATHLETE_PUBLIC_ID]


@pytest.mark.parametrize(
    "roles",
    [(SystemRoleCode.ATHLETE,), (SystemRoleCode.TRAINER,)],
)
async def test_non_administrative_roles_are_forbidden(
    roles: tuple[SystemRoleCode, ...],
) -> None:
    interactor, athletes, codec = make_interactor(roles=roles)

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(
            ResolveAthleteQrQuery(
                actor_telegram_id=ACTOR_TELEGRAM_ID,
                athlete_qr_token="signed-athlete-token",
            )
        )

    assert codec.verified_tokens == []
    assert athletes.requested_public_ids == []


@pytest.mark.parametrize(
    "codec_error",
    [
        AthleteQrTokenExpiredError(),
        AthleteQrTokenInvalidSignatureError(),
        AthleteQrTokenMalformedPayloadError(),
    ],
)
async def test_existing_qr_codec_errors_remain_controlled(
    codec_error: Exception,
) -> None:
    interactor, athletes, _ = make_interactor(
        roles=(SystemRoleCode.ADMINISTRATOR,),
        codec_error=codec_error,
    )

    with pytest.raises(type(codec_error)):
        await interactor(
            ResolveAthleteQrQuery(
                actor_telegram_id=ACTOR_TELEGRAM_ID,
                athlete_qr_token="invalid-token",
            )
        )

    assert athletes.requested_public_ids == []


async def test_valid_token_for_missing_athlete_is_not_found() -> None:
    interactor, athletes, _ = make_interactor(
        roles=(SystemRoleCode.OWNER,)
    )
    athletes.athlete = None

    with pytest.raises(AthleteNotFoundError):
        await interactor(
            ResolveAthleteQrQuery(
                actor_telegram_id=ACTOR_TELEGRAM_ID,
                athlete_qr_token="signed-athlete-token",
            )
        )


@pytest.mark.parametrize(
    "subscription_state",
    ["missing", "expired", "remaining_visits_zero"],
)
async def test_subscription_state_does_not_participate_in_resolution(
    subscription_state: str,
) -> None:
    interactor, _, _ = make_interactor(
        roles=(SystemRoleCode.ADMINISTRATOR,)
    )

    result = await interactor(
        ResolveAthleteQrQuery(
            actor_telegram_id=ACTOR_TELEGRAM_ID,
            athlete_qr_token="signed-athlete-token",
        )
    )

    assert subscription_state in {
        "missing",
        "expired",
        "remaining_visits_zero",
    }
    assert result.full_name == "Иван Иванов"
