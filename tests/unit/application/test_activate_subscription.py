from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from uuid import uuid4

import pytest

from application.club.errors import TrainingGroupNotFoundError
from application.identity.errors import AdministratorPermissionRequiredError
from application.subscriptions import (
    ActivateSubscriptionCommand,
    ActivateSubscriptionInteractor,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    SubscriptionGroupForbiddenError,
    SubscriptionGroupRequiredError,
    SubscriptionPlanInactiveError,
    SubscriptionPlanNotApplicableToGroupError,
    SubscriptionPlanNotFoundError,
)
from domain.club import TrainingGroup, TrainingGroupType
from domain.identity import Athlete, SystemRoleCode, User
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionPlan,
    SubscriptionStatus,
)

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)
ACTOR_TELEGRAM_ID = 12345
ACTOR_USER_ID = 10
ATHLETE_ID = 20
PLAN_ID = 30
GROUP_ID = 40


class FrozenClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self._now


class FakeUserRepository:
    def __init__(self) -> None:
        self.actor = User(
            id=ACTOR_USER_ID,
            telegram_id=ACTOR_TELEGRAM_ID,
            username="admin",
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self.actor if telegram_id == ACTOR_TELEGRAM_ID else None


class FakeRoleRepository:
    def __init__(self, role: SystemRoleCode) -> None:
        self.role = role

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return (self.role,) if user_id == ACTOR_USER_ID else ()


class FakeAthleteRepository:
    def __init__(self) -> None:
        self.athlete = Athlete(
            id=ATHLETE_ID,
            athlete_public_id=uuid4(),
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            birth_date=date(1991, 12, 27),
            phone=None,
            is_active=True,
        )
        self.locked_ids: list[int] = []

    async def get_by_id_for_update(
        self,
        athlete_id: int,
    ) -> Athlete | None:
        self.locked_ids.append(athlete_id)
        return self.athlete if athlete_id == ATHLETE_ID else None


class FakeTrainingGroupRepository:
    def __init__(
        self,
        group_type: TrainingGroupType = TrainingGroupType.REGULAR,
    ) -> None:
        self.group = TrainingGroup(
            id=GROUP_ID,
            trainer_id=None,
            group_type=group_type,
        )

    async def get_by_id(
        self,
        training_group_id: int,
    ) -> TrainingGroup | None:
        return self.group if training_group_id == GROUP_ID else None


class FakePlanRepository:
    def __init__(self, plan: SubscriptionPlan | None) -> None:
        self.plan = plan

    async def get_by_id(
        self,
        subscription_plan_id: int,
    ) -> SubscriptionPlan | None:
        if self.plan is None or self.plan.id != subscription_plan_id:
            return None
        return self.plan


class FakeSubscriptionRepository:
    def __init__(
        self,
        current: Subscription | None = None,
        *,
        events: list[str] | None = None,
        add_error: BaseException | None = None,
    ) -> None:
        self.current = current
        self.events = events if events is not None else []
        self.added: list[Subscription] = []
        self.expired_ids: list[int] = []
        self.add_error = add_error

    async def get_active_by_athlete(
        self,
        athlete_id: int,
    ) -> Subscription | None:
        return self.current

    async def mark_expired(self, subscription_id: int) -> bool:
        self.events.append("expire")
        self.expired_ids.append(subscription_id)
        return True

    async def add(self, subscription: Subscription) -> int:
        self.events.append("add")
        if self.add_error is not None:
            raise self.add_error
        self.added.append(subscription)
        return 99


class FakeAuditLogRepository:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
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
        self.events.append("audit")
        self.records.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
            }
        )


class FakeUnitOfWork:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.commit_calls = 0
        self.flush_calls = 0
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_exception = exc_type

    async def flush(self) -> None:
        self.events.append("flush")
        self.flush_calls += 1

    async def commit(self) -> None:
        self.events.append("commit")
        self.commit_calls += 1


def make_plan(
    *,
    access_scope: SubscriptionAccessScope = (
        SubscriptionAccessScope.SPECIFIC_GROUP
    ),
    required_group_type: TrainingGroupType | None = None,
    visit_limit: int | None = 8,
    duration_months: int = 1,
    is_active: bool = True,
) -> SubscriptionPlan:
    return SubscriptionPlan(
        id=PLAN_ID,
        code="TEST_PLAN",
        name="Тестовый тариф",
        visit_limit=visit_limit,
        duration_months=duration_months,
        price=Decimal("4000"),
        is_unlimited=visit_limit is None,
        access_scope=access_scope,
        required_group_type=required_group_type,
        is_active=is_active,
    )


def make_current_subscription(
    *,
    expires_at: datetime,
) -> Subscription:
    return Subscription(
        id=55,
        athlete_id=ATHLETE_ID,
        group_id=GROUP_ID,
        plan_id=PLAN_ID,
        activated_by_user_id=ACTOR_USER_ID,
        activated_at=NOW - timedelta(days=30),
        starts_at=NOW - timedelta(days=30),
        expires_at=expires_at,
        activation_price=Decimal("4000"),
        remaining_visits=1,
        status=SubscriptionStatus.ACTIVE,
    )


def make_interactor(
    *,
    role: SystemRoleCode = SystemRoleCode.ADMINISTRATOR,
    plan: SubscriptionPlan | None = None,
    group_type: TrainingGroupType = TrainingGroupType.REGULAR,
    current: Subscription | None = None,
    now: datetime = NOW,
    events: list[str] | None = None,
    add_error: BaseException | None = None,
) -> tuple[
    ActivateSubscriptionInteractor,
    FakeSubscriptionRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
    FrozenClock,
]:
    shared_events = events if events is not None else []
    subscriptions = FakeSubscriptionRepository(
        current,
        events=shared_events,
        add_error=add_error,
    )
    audit = FakeAuditLogRepository(shared_events)
    uow = FakeUnitOfWork(shared_events)
    clock = FrozenClock(now)
    return (
        ActivateSubscriptionInteractor(
            user_repository=FakeUserRepository(),
            athlete_repository=FakeAthleteRepository(),
            role_repository=FakeRoleRepository(role),
            training_group_repository=FakeTrainingGroupRepository(group_type),
            subscription_plan_repository=FakePlanRepository(
                plan if plan is not None else make_plan()
            ),
            subscription_repository=subscriptions,
            audit_log_repository=audit,
            unit_of_work=uow,
            clock=clock,
        ),
        subscriptions,
        audit,
        uow,
        clock,
    )


def command(*, group_id: int | None = GROUP_ID) -> ActivateSubscriptionCommand:
    return ActivateSubscriptionCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        athlete_id=ATHLETE_ID,
        subscription_plan_id=PLAN_ID,
        training_group_id=group_id,
    )


@pytest.mark.parametrize(
    "role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_actor_activates_specific_group_subscription(
    role: SystemRoleCode,
) -> None:
    interactor, subscriptions, audit, uow, clock = make_interactor(role=role)

    result = await interactor(command())

    assert result.subscription_id == 99
    assert result.remaining_visits == 8
    created = subscriptions.added[0]
    assert created.group_id == GROUP_ID
    assert created.status is SubscriptionStatus.ACTIVE
    assert created.starts_at == NOW
    assert created.expires_at == datetime(2026, 9, 26, 12, tzinfo=UTC)
    assert created.remaining_visits == 8
    assert audit.records[0]["actor_user_id"] == ACTOR_USER_ID
    assert audit.records[0]["action"] == "SUBSCRIPTION_ACTIVATED"
    assert uow.commit_calls == 1
    assert clock.calls == 1


@pytest.mark.parametrize(
    "role",
    [SystemRoleCode.TRAINER, SystemRoleCode.ATHLETE],
)
async def test_non_administrative_actor_is_forbidden(
    role: SystemRoleCode,
) -> None:
    interactor, subscriptions, audit, uow, _ = make_interactor(role=role)

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(command())

    assert not subscriptions.added
    assert not audit.records
    assert uow.commit_calls == 0


async def test_unlimited_subscription_has_no_group_or_remaining_visits() -> None:
    interactor, subscriptions, _, _, _ = make_interactor(
        plan=make_plan(
            access_scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
            visit_limit=None,
        )
    )

    result = await interactor(command(group_id=None))

    assert result.training_group_id is None
    assert result.remaining_visits is None
    assert subscriptions.added[0].group_id is None
    assert subscriptions.added[0].remaining_visits is None


async def test_specific_group_plan_requires_group() -> None:
    interactor, subscriptions, audit, uow, _ = make_interactor()

    with pytest.raises(SubscriptionGroupRequiredError):
        await interactor(command(group_id=None))

    assert not subscriptions.added
    assert not audit.records
    assert uow.commit_calls == 0


async def test_unlimited_plan_forbids_group() -> None:
    interactor, subscriptions, _, _, _ = make_interactor(
        plan=make_plan(
            access_scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
            visit_limit=None,
        )
    )

    with pytest.raises(SubscriptionGroupForbiddenError):
        await interactor(command())

    assert not subscriptions.added


async def test_missing_group_is_controlled() -> None:
    interactor, _, _, _, _ = make_interactor()

    with pytest.raises(TrainingGroupNotFoundError):
        await interactor(command(group_id=999))


async def test_mini_plan_accepts_only_mini_group() -> None:
    plan = make_plan(required_group_type=TrainingGroupType.MINI)
    incompatible, _, _, _, _ = make_interactor(plan=plan)

    with pytest.raises(SubscriptionPlanNotApplicableToGroupError):
        await incompatible(command())

    compatible, subscriptions, _, _, _ = make_interactor(
        plan=plan,
        group_type=TrainingGroupType.MINI,
    )
    await compatible(command())
    assert subscriptions.added[0].group_id == GROUP_ID


async def test_generic_specific_group_plan_accepts_mini_group() -> None:
    interactor, subscriptions, _, _, _ = make_interactor(
        group_type=TrainingGroupType.MINI
    )

    await interactor(command())

    assert subscriptions.added[0].group_id == GROUP_ID


async def test_inactive_plan_is_rejected() -> None:
    interactor, subscriptions, audit, uow, _ = make_interactor(
        plan=make_plan(is_active=False)
    )

    with pytest.raises(SubscriptionPlanInactiveError):
        await interactor(command())

    assert not subscriptions.added
    assert not audit.records
    assert uow.commit_calls == 0


async def test_missing_plan_is_rejected() -> None:
    interactor, subscriptions, _, _, _ = make_interactor()
    interactor._plans = FakePlanRepository(None)  # noqa: SLF001

    with pytest.raises(SubscriptionPlanNotFoundError):
        await interactor(command())

    assert not subscriptions.added


async def test_non_elapsed_active_subscription_blocks_activation() -> None:
    current = make_current_subscription(expires_at=NOW + timedelta(seconds=1))
    interactor, subscriptions, audit, uow, _ = make_interactor(current=current)

    with pytest.raises(ActiveSubscriptionAlreadyExistsError):
        await interactor(command())

    assert not subscriptions.expired_ids
    assert not subscriptions.added
    assert not audit.records
    assert uow.commit_calls == 0


async def test_stale_active_is_flushed_before_new_active_insert() -> None:
    events: list[str] = []
    current = make_current_subscription(expires_at=NOW)
    interactor, subscriptions, _, uow, _ = make_interactor(
        current=current,
        events=events,
    )

    await interactor(command())

    assert subscriptions.expired_ids == [55]
    assert uow.flush_calls == 1
    assert events == ["expire", "flush", "add", "audit", "commit"]


async def test_lazy_expiration_is_rolled_back_with_later_validation_error() -> None:
    current = make_current_subscription(expires_at=NOW - timedelta(seconds=1))
    interactor, subscriptions, audit, uow, _ = make_interactor(current=current)
    interactor._plans = FakePlanRepository(None)  # noqa: SLF001

    with pytest.raises(SubscriptionPlanNotFoundError):
        await interactor(command())

    assert subscriptions.expired_ids == [55]
    assert uow.flush_calls == 1
    assert uow.commit_calls == 0
    assert uow.exit_exception is SubscriptionPlanNotFoundError
    assert not audit.records


async def test_controlled_unique_conflict_does_not_create_audit() -> None:
    conflict = ActiveSubscriptionAlreadyExistsError()
    interactor, _, audit, uow, _ = make_interactor(add_error=conflict)

    with pytest.raises(ActiveSubscriptionAlreadyExistsError):
        await interactor(command())

    assert not audit.records
    assert uow.commit_calls == 0


@pytest.mark.parametrize(
    ("now", "duration_months", "expected"),
    [
        (
            datetime(2026, 8, 26, 12, tzinfo=UTC),
            1,
            datetime(2026, 9, 26, 12, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 26, 12, tzinfo=UTC),
            3,
            datetime(2026, 11, 26, 12, tzinfo=UTC),
        ),
        (
            datetime(2026, 1, 31, 12, tzinfo=UTC),
            1,
            datetime(2026, 2, 28, 12, tzinfo=UTC),
        ),
    ],
)
async def test_expiration_uses_calendar_months(
    now: datetime,
    duration_months: int,
    expected: datetime,
) -> None:
    interactor, subscriptions, _, _, _ = make_interactor(
        plan=make_plan(duration_months=duration_months),
        now=now,
    )

    await interactor(command())

    assert subscriptions.added[0].expires_at == expected
