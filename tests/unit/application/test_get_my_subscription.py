from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from application.identity.errors import (
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
)
from application.subscriptions import (
    AthleteSubscriptionReadModel,
    GetMySubscriptionInteractor,
    GetMySubscriptionQuery,
    MySubscriptionGroup,
    PersistedActiveSubscriptionReadModel,
)
from domain.identity import SystemRoleCode, User
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)
TELEGRAM_ID = 12345
USER_ID = 10
ATHLETE_ID = 20


class FrozenClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class FakeUserRepository:
    def __init__(self, user: User | None = None) -> None:
        self.user = user if user is not None else registered_user()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self.user if telegram_id == TELEGRAM_ID else None


class FakeRoleRepository:
    def __init__(self, roles: tuple[SystemRoleCode, ...]) -> None:
        self.roles = roles

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.roles if user_id == USER_ID else ()


class FakeMySubscriptionReader:
    def __init__(
        self,
        read_model: AthleteSubscriptionReadModel | None,
    ) -> None:
        self.read_model = read_model
        self.requested_user_ids: list[int] = []

    async def get_by_user_id(
        self,
        user_id: int,
    ) -> AthleteSubscriptionReadModel | None:
        self.requested_user_ids.append(user_id)
        return self.read_model


def registered_user() -> User:
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


def subscription(
    *,
    starts_at: datetime = NOW - timedelta(days=5),
    expires_at: datetime = NOW + timedelta(days=25),
    remaining_visits: int | None = 7,
    group_id: int | None = 30,
) -> Subscription:
    return Subscription(
        id=40,
        athlete_id=ATHLETE_ID,
        group_id=group_id,
        plan_id=50,
        activated_by_user_id=60,
        activated_at=starts_at,
        starts_at=starts_at,
        expires_at=expires_at,
        activation_price=Decimal("6000"),
        remaining_visits=remaining_visits,
        status=SubscriptionStatus.ACTIVE,
    )


def read_model(
    current: Subscription | None,
    *,
    unlimited: bool = False,
) -> AthleteSubscriptionReadModel:
    if current is None:
        return AthleteSubscriptionReadModel(
            athlete_id=ATHLETE_ID,
            persisted_active=None,
        )
    group = (
        None
        if unlimited
        else MySubscriptionGroup(
            training_group_id=30,
            direction_name="Кикбоксинг",
            group_name="Взрослые",
        )
    )
    return AthleteSubscriptionReadModel(
        athlete_id=ATHLETE_ID,
        persisted_active=PersistedActiveSubscriptionReadModel(
            subscription=current,
            plan_name="Безлимит" if unlimited else "12 посещений",
            is_unlimited=unlimited,
            access_scope=(
                SubscriptionAccessScope.ALL_REGULAR_GROUPS
                if unlimited
                else SubscriptionAccessScope.SPECIFIC_GROUP
            ),
            group=group,
        ),
    )


def make_interactor(
    source: AthleteSubscriptionReadModel | None,
    *,
    roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.ATHLETE,),
) -> tuple[
    GetMySubscriptionInteractor,
    FakeMySubscriptionReader,
    FrozenClock,
]:
    reader = FakeMySubscriptionReader(source)
    clock = FrozenClock()
    return (
        GetMySubscriptionInteractor(
            user_repository=FakeUserRepository(),
            role_repository=FakeRoleRepository(roles),
            reader=reader,
            clock=clock,
        ),
        reader,
        clock,
    )


def query() -> GetMySubscriptionQuery:
    return GetMySubscriptionQuery(actor_telegram_id=TELEGRAM_ID)


async def test_returns_stored_remaining_visits_for_effective_limited() -> None:
    interactor, reader, clock = make_interactor(
        read_model(subscription(remaining_visits=7))
    )

    result = await interactor(query())

    assert result.current is not None
    assert result.current.plan_name == "12 посещений"
    assert result.current.remaining_visits == 7
    assert result.current.group == MySubscriptionGroup(
        training_group_id=30,
        direction_name="Кикбоксинг",
        group_name="Взрослые",
    )
    assert reader.requested_user_ids == [USER_ID]
    assert clock.calls == 1


async def test_returns_unlimited_without_group_or_remaining_visits() -> None:
    current = subscription(remaining_visits=None, group_id=None)
    interactor, _, _ = make_interactor(read_model(current, unlimited=True))

    result = await interactor(query())

    assert result.current is not None
    assert result.current.is_unlimited is True
    assert result.current.access_scope is (
        SubscriptionAccessScope.ALL_REGULAR_GROUPS
    )
    assert result.current.group is None
    assert result.current.remaining_visits is None


@pytest.mark.parametrize(
    "current",
    [
        subscription(expires_at=NOW - timedelta(seconds=1)),
        subscription(expires_at=NOW),
        subscription(starts_at=NOW + timedelta(seconds=1)),
    ],
)
async def test_non_effective_persisted_active_is_absent_without_mutation(
    current: Subscription,
) -> None:
    interactor, _, clock = make_interactor(read_model(current))

    result = await interactor(query())

    assert result.current is None
    assert current.status is SubscriptionStatus.ACTIVE
    assert clock.calls == 1


async def test_no_persisted_active_returns_no_active_state() -> None:
    interactor, _, clock = make_interactor(read_model(None))

    result = await interactor(query())

    assert result.current is None
    assert clock.calls == 1


async def test_zero_remaining_visits_stays_visible() -> None:
    interactor, _, _ = make_interactor(
        read_model(subscription(remaining_visits=0))
    )

    result = await interactor(query())

    assert result.current is not None
    assert result.current.remaining_visits == 0


async def test_missing_linked_athlete_is_controlled() -> None:
    interactor, _, clock = make_interactor(None)

    with pytest.raises(AthleteProfileNotFoundError):
        await interactor(query())

    assert clock.calls == 0


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
    interactor, _, _ = make_interactor(read_model(None), roles=roles)

    result = await interactor(query())

    assert result.current is None


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
    interactor, reader, clock = make_interactor(
        read_model(None),
        roles=(role,),
    )

    with pytest.raises(AthletePermissionRequiredError):
        await interactor(query())

    assert not reader.requested_user_ids
    assert clock.calls == 0
