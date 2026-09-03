from datetime import UTC, datetime

import pytest

from application.identity.errors import AdministratorPermissionRequiredError
from application.subscriptions import (
    AthleteLatestSubscriptionReadModel,
    GetLatestAthleteSubscriptionInteractor,
    GetLatestAthleteSubscriptionQuery,
)
from domain.identity import SystemRoleCode, User

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


class FakeUsers:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return User(1, telegram_id, None, "Admin", "User", True, NOW, NOW)


class FakeRoles:
    def __init__(self, role: SystemRoleCode) -> None:
        self.role = role

    async def list_active_codes_for_user(
        self, user_id: int
    ) -> tuple[SystemRoleCode, ...]:
        return (self.role,)


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def get_by_athlete_id(
        self, athlete_id: int
    ) -> AthleteLatestSubscriptionReadModel | None:
        self.calls.append(athlete_id)
        return AthleteLatestSubscriptionReadModel(
            athlete_id=athlete_id,
            athlete_full_name="Иван Иванов",
            latest=None,
        )


@pytest.mark.parametrize(
    "role", [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER]
)
async def test_administrative_actor_reads_latest_or_no_subscription(
    role: SystemRoleCode,
) -> None:
    reader = FakeReader()
    interactor = GetLatestAthleteSubscriptionInteractor(
        FakeUsers(), FakeRoles(role), reader
    )

    result = await interactor(GetLatestAthleteSubscriptionQuery(123, 20))

    assert result.athlete_id == 20
    assert result.latest is None
    assert reader.calls == [20]


@pytest.mark.parametrize(
    "role", [SystemRoleCode.TRAINER, SystemRoleCode.ATHLETE]
)
async def test_non_administrative_actor_cannot_read_latest(
    role: SystemRoleCode,
) -> None:
    reader = FakeReader()
    interactor = GetLatestAthleteSubscriptionInteractor(
        FakeUsers(), FakeRoles(role), reader
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(GetLatestAthleteSubscriptionQuery(123, 20))

    assert not reader.calls
