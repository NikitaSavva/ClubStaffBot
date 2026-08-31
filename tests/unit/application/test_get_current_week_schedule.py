from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
    TrainerPermissionRequiredError,
)
from application.subscriptions import (
    AthleteSubscriptionReadModel,
    PersistedActiveSubscriptionReadModel,
)
from application.training_sessions import (
    CurrentWeekScheduleFilters,
    GetCurrentWeekScheduleInteractor,
    GetCurrentWeekScheduleQuery,
    ScheduleSessionItem,
)
from domain.club import (
    TrainingGroupType,
    TrainingSessionStatus,
)
from domain.identity import SystemRoleCode, User
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 8, 26, 12, tzinfo=CLUB_TIMEZONE)
TELEGRAM_ID = 12345
USER_ID = 10
ATHLETE_ID = 20
GROUP_ID = 30


class FrozenClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.value = now
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class FakeUserRepository:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return registered_user() if telegram_id == TELEGRAM_ID else None


class FakeRoleRepository:
    def __init__(self, roles: tuple[SystemRoleCode, ...]) -> None:
        self.roles = roles

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.roles if user_id == USER_ID else ()


class FakeSubscriptionReader:
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


class FakeScheduleReader:
    def __init__(
        self,
        sessions: tuple[ScheduleSessionItem, ...] = (),
    ) -> None:
        self.sessions = sessions
        self.filters: list[CurrentWeekScheduleFilters] = []

    async def list(
        self,
        filters: CurrentWeekScheduleFilters,
    ) -> tuple[ScheduleSessionItem, ...]:
        self.filters.append(filters)
        return self.sessions


def registered_user() -> User:
    return User(
        id=USER_ID,
        telegram_id=TELEGRAM_ID,
        username="actor",
        first_name="Иван",
        last_name="Иванов",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )


def subscription(
    *,
    access_scope: SubscriptionAccessScope = (
        SubscriptionAccessScope.SPECIFIC_GROUP
    ),
    starts_at: datetime = NOW - timedelta(days=5),
    expires_at: datetime = NOW + timedelta(days=25),
    remaining_visits: int | None = 7,
) -> PersistedActiveSubscriptionReadModel:
    group_id = (
        GROUP_ID
        if access_scope is SubscriptionAccessScope.SPECIFIC_GROUP
        else None
    )
    return PersistedActiveSubscriptionReadModel(
        subscription=Subscription(
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
        ),
        plan_name="Безлимит",
        is_unlimited=(
            access_scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS
        ),
        access_scope=access_scope,
        group=None,
    )


def athlete_read_model(
    persisted: PersistedActiveSubscriptionReadModel | None,
) -> AthleteSubscriptionReadModel:
    return AthleteSubscriptionReadModel(
        athlete_id=ATHLETE_ID,
        persisted_active=persisted,
    )


def schedule_item(
    *,
    starts_at: datetime,
) -> ScheduleSessionItem:
    return ScheduleSessionItem(
        id=1,
        training_group_id=GROUP_ID,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=90),
        status=TrainingSessionStatus.SCHEDULED,
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые",
    )


def make_interactor(
    *,
    roles: tuple[SystemRoleCode, ...],
    persisted: PersistedActiveSubscriptionReadModel | None = None,
    athlete_model_exists: bool = True,
    sessions: tuple[ScheduleSessionItem, ...] = (),
    now: datetime = NOW,
) -> tuple[
    GetCurrentWeekScheduleInteractor,
    FakeSubscriptionReader,
    FakeScheduleReader,
    FrozenClock,
]:
    subscription_reader = FakeSubscriptionReader(
        athlete_read_model(persisted) if athlete_model_exists else None
    )
    schedule_reader = FakeScheduleReader(sessions)
    clock = FrozenClock(now)
    return (
        GetCurrentWeekScheduleInteractor(
            user_repository=FakeUserRepository(),
            role_repository=FakeRoleRepository(roles),
            subscription_reader=subscription_reader,
            schedule_reader=schedule_reader,
            clock=clock,
            club_timezone=CLUB_TIMEZONE,
        ),
        subscription_reader,
        schedule_reader,
        clock,
    )


async def test_specific_group_uses_local_week_and_group_filter() -> None:
    monday_local = datetime(2026, 8, 24, 9, tzinfo=CLUB_TIMEZONE)
    friday_local = datetime(2026, 8, 28, 19, tzinfo=CLUB_TIMEZONE)
    interactor, _, reader, clock = make_interactor(
        roles=(SystemRoleCode.ATHLETE,),
        persisted=subscription(),
        sessions=(
            schedule_item(starts_at=monday_local.astimezone(UTC)),
            schedule_item(starts_at=friday_local.astimezone(UTC)),
        ),
    )

    result = await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=SystemRoleCode.ATHLETE,
        )
    )

    assert reader.filters == [
        CurrentWeekScheduleFilters(
            week_start=datetime(2026, 8, 23, 21, tzinfo=UTC),
            week_end=datetime(2026, 8, 29, 21, tzinfo=UTC),
            training_group_id=GROUP_ID,
        )
    ]
    assert result.schedule is not None
    assert result.schedule.week_start == datetime(
        2026, 8, 24, tzinfo=CLUB_TIMEZONE
    )
    assert result.schedule.week_end == datetime(
        2026, 8, 30, tzinfo=CLUB_TIMEZONE
    )
    assert [item.starts_at for item in result.schedule.sessions] == [
        monday_local,
        friday_local,
    ]
    assert clock.calls == 1


async def test_unlimited_filters_regular_groups() -> None:
    interactor, _, reader, _ = make_interactor(
        roles=(SystemRoleCode.ATHLETE,),
        persisted=subscription(
            access_scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
            remaining_visits=None,
        ),
    )

    result = await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=SystemRoleCode.ATHLETE,
        )
    )

    assert result.schedule is not None
    assert reader.filters[0].group_type is TrainingGroupType.REGULAR
    assert reader.filters[0].training_group_id is None


async def test_zero_remaining_visits_do_not_block_specific_schedule() -> None:
    interactor, _, reader, _ = make_interactor(
        roles=(SystemRoleCode.ATHLETE,),
        persisted=subscription(remaining_visits=0),
    )

    result = await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=SystemRoleCode.ATHLETE,
        )
    )

    assert result.schedule is not None
    assert reader.filters[0].training_group_id == GROUP_ID


@pytest.mark.parametrize(
    "persisted",
    [
        None,
        subscription(expires_at=NOW),
        subscription(starts_at=NOW + timedelta(seconds=1)),
    ],
)
async def test_no_effective_subscription_skips_schedule_query(
    persisted: PersistedActiveSubscriptionReadModel | None,
) -> None:
    interactor, _, reader, clock = make_interactor(
        roles=(SystemRoleCode.ATHLETE,),
        persisted=persisted,
    )

    result = await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=SystemRoleCode.ATHLETE,
        )
    )

    assert result.schedule is None
    assert not reader.filters
    assert clock.calls == 1
    if persisted is not None:
        assert persisted.subscription.status is SubscriptionStatus.ACTIVE


async def test_missing_athlete_profile_is_controlled() -> None:
    interactor, _, reader, _ = make_interactor(
        roles=(SystemRoleCode.ATHLETE,),
        athlete_model_exists=False,
    )

    with pytest.raises(AthleteProfileNotFoundError):
        await interactor(
            GetCurrentWeekScheduleQuery(
                actor_telegram_id=TELEGRAM_ID,
                selected_role=SystemRoleCode.ATHLETE,
            )
        )

    assert not reader.filters


async def test_trainer_uses_training_session_snapshot_filter() -> None:
    interactor, subscription_reader, reader, _ = make_interactor(
        roles=(SystemRoleCode.TRAINER,),
    )

    await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=SystemRoleCode.TRAINER,
        )
    )

    assert reader.filters[0].trainer_id == USER_ID
    assert not subscription_reader.requested_user_ids


@pytest.mark.parametrize(
    "role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_roles_use_unfiltered_schedule_scope(
    role: SystemRoleCode,
) -> None:
    interactor, _, reader, _ = make_interactor(roles=(role,))

    await interactor(
        GetCurrentWeekScheduleQuery(
            actor_telegram_id=TELEGRAM_ID,
            selected_role=role,
        )
    )

    assert reader.filters == [
        CurrentWeekScheduleFilters(
            week_start=datetime(2026, 8, 23, 21, tzinfo=UTC),
            week_end=datetime(2026, 8, 29, 21, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize(
    ("selected_role", "assigned_role", "error"),
    [
        (
            SystemRoleCode.ATHLETE,
            SystemRoleCode.TRAINER,
            AthletePermissionRequiredError,
        ),
        (
            SystemRoleCode.TRAINER,
            SystemRoleCode.ATHLETE,
            TrainerPermissionRequiredError,
        ),
        (
            SystemRoleCode.ADMINISTRATOR,
            SystemRoleCode.OWNER,
            AdministratorPermissionRequiredError,
        ),
        (
            SystemRoleCode.OWNER,
            SystemRoleCode.ADMINISTRATOR,
            AdministratorPermissionRequiredError,
        ),
    ],
)
async def test_selected_role_is_not_trusted_for_authorization(
    selected_role: SystemRoleCode,
    assigned_role: SystemRoleCode,
    error: type[Exception],
) -> None:
    interactor, _, reader, clock = make_interactor(roles=(assigned_role,))

    with pytest.raises(error):
        await interactor(
            GetCurrentWeekScheduleQuery(
                actor_telegram_id=TELEGRAM_ID,
                selected_role=selected_role,
            )
        )

    assert not reader.filters
    assert clock.calls == 0
