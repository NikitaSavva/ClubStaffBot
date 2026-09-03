from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from uuid import uuid4

import pytest

from application.identity.errors import AdministratorPermissionRequiredError
from application.subscriptions import (
    CorrectSubscriptionCommand,
    CorrectSubscriptionInteractor,
    CorrectSubscriptionOutcome,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    InvalidRemainingVisitsError,
    InvalidSubscriptionExpirationError,
    LatestSubscriptionChangedError,
    LimitedSubscriptionRemainingVisitsRequiredError,
    SubscriptionNotFoundError,
    UnlimitedSubscriptionRemainingVisitsForbiddenError,
)
from domain.identity import Athlete, SystemRoleCode, User
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionPlan,
    SubscriptionStatus,
)

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
ACTOR_TELEGRAM_ID = 100
ACTOR_USER_ID = 10
ATHLETE_ID = 20
SUBSCRIPTION_ID = 30
PLAN_ID = 40


class FakeUserRepository:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id != ACTOR_TELEGRAM_ID:
            return None
        return User(
            id=ACTOR_USER_ID,
            telegram_id=telegram_id,
            username="admin",
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )


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
        self.locked_ids: list[int] = []

    async def get_by_id_for_update(self, athlete_id: int) -> Athlete | None:
        self.locked_ids.append(athlete_id)
        if athlete_id != ATHLETE_ID:
            return None
        return Athlete(
            id=ATHLETE_ID,
            athlete_public_id=uuid4(),
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            birth_date=date(1991, 12, 27),
            phone=None,
            is_active=True,
        )


class FakePlanRepository:
    def __init__(self, *, unlimited: bool = False) -> None:
        self.plan = SubscriptionPlan(
            id=PLAN_ID,
            code="TEST",
            name="Тест",
            visit_limit=None if unlimited else 12,
            duration_months=1,
            price=Decimal("5000"),
            is_unlimited=unlimited,
            access_scope=(
                SubscriptionAccessScope.ALL_REGULAR_GROUPS
                if unlimited
                else SubscriptionAccessScope.SPECIFIC_GROUP
            ),
            required_group_type=None,
            is_active=True,
        )

    async def get_by_id(
        self,
        subscription_plan_id: int,
    ) -> SubscriptionPlan | None:
        return self.plan if subscription_plan_id == PLAN_ID else None


class FakeSubscriptionRepository:
    def __init__(
        self,
        current: Subscription,
        *,
        latest_id: int = SUBSCRIPTION_ID,
        other_active: Subscription | None = None,
    ) -> None:
        self.current = current
        self.latest_id = latest_id
        self.other_active = other_active
        self.locked_ids: list[int] = []
        self.other_active_checks: list[tuple[int, int]] = []
        self.updates: list[dict[str, object]] = []

    async def get_by_id_for_update(
        self,
        subscription_id: int,
    ) -> Subscription | None:
        self.locked_ids.append(subscription_id)
        return self.current if subscription_id == self.current.id else None

    async def get_latest_id_by_athlete(self, athlete_id: int) -> int | None:
        return self.latest_id if athlete_id == ATHLETE_ID else None

    async def get_other_active_by_athlete(
        self,
        *,
        athlete_id: int,
        excluded_subscription_id: int,
    ) -> Subscription | None:
        self.other_active_checks.append(
            (athlete_id, excluded_subscription_id)
        )
        return self.other_active

    async def update_correction(
        self,
        *,
        subscription_id: int,
        remaining_visits: int | None,
        expires_at: datetime,
        status: SubscriptionStatus,
    ) -> bool:
        self.updates.append(
            {
                "subscription_id": subscription_id,
                "remaining_visits": remaining_visits,
                "expires_at": expires_at,
                "status": status,
            }
        )
        return subscription_id == self.current.id


class FakeAuditLogRepository:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.records: list[dict[str, object]] = []

    async def add(self, **record: object) -> None:
        if self.error is not None:
            raise self.error
        self.records.append(record)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commit_calls = 0
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
        return None

    async def commit(self) -> None:
        self.commit_calls += 1


def subscription(
    *,
    athlete_id: int = ATHLETE_ID,
    remaining_visits: int | None = 12,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> Subscription:
    return Subscription(
        id=SUBSCRIPTION_ID,
        athlete_id=athlete_id,
        group_id=50,
        plan_id=PLAN_ID,
        activated_by_user_id=ACTOR_USER_ID,
        activated_at=NOW - timedelta(days=10),
        starts_at=NOW - timedelta(days=10),
        expires_at=NOW + timedelta(days=20),
        activation_price=Decimal("5000"),
        remaining_visits=remaining_visits,
        status=status,
    )


def command(
    *,
    athlete_id: int = ATHLETE_ID,
    remaining_visits_is_set: bool = False,
    remaining_visits: int | None = None,
    expires_at: datetime | None = None,
    status: SubscriptionStatus | None = None,
) -> CorrectSubscriptionCommand:
    return CorrectSubscriptionCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        athlete_id=athlete_id,
        subscription_id=SUBSCRIPTION_ID,
        remaining_visits_is_set=remaining_visits_is_set,
        remaining_visits=remaining_visits,
        expires_at=expires_at,
        status=status,
    )


def make_interactor(
    *,
    current: Subscription | None = None,
    role: SystemRoleCode = SystemRoleCode.ADMINISTRATOR,
    unlimited: bool = False,
    latest_id: int = SUBSCRIPTION_ID,
    other_active: Subscription | None = None,
    audit_error: BaseException | None = None,
) -> tuple[
    CorrectSubscriptionInteractor,
    FakeAthleteRepository,
    FakeSubscriptionRepository,
    FakeAuditLogRepository,
    FakeUnitOfWork,
]:
    source = current or subscription(
        remaining_visits=None if unlimited else 12
    )
    athletes = FakeAthleteRepository()
    subscriptions = FakeSubscriptionRepository(
        source,
        latest_id=latest_id,
        other_active=other_active,
    )
    audit = FakeAuditLogRepository(audit_error)
    uow = FakeUnitOfWork()
    return (
        CorrectSubscriptionInteractor(
            user_repository=FakeUserRepository(),
            athlete_repository=athletes,
            role_repository=FakeRoleRepository(role),
            subscription_plan_repository=FakePlanRepository(
                unlimited=unlimited
            ),
            subscription_repository=subscriptions,
            audit_log_repository=audit,
            unit_of_work=uow,
        ),
        athletes,
        subscriptions,
        audit,
        uow,
    )


@pytest.mark.parametrize(
    "role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_corrects_multiple_fields_with_one_audit(
    role: SystemRoleCode,
) -> None:
    interactor, athletes, subscriptions, audit, uow = make_interactor(role=role)
    corrected_expiry = NOW + timedelta(days=5)

    result = await interactor(
        command(
            remaining_visits_is_set=True,
            remaining_visits=7,
            expires_at=corrected_expiry,
            status=SubscriptionStatus.EXPIRED,
        )
    )

    assert result.outcome is CorrectSubscriptionOutcome.CORRECTED
    assert athletes.locked_ids == [ATHLETE_ID]
    assert subscriptions.locked_ids == [SUBSCRIPTION_ID]
    assert subscriptions.updates == [
        {
            "subscription_id": SUBSCRIPTION_ID,
            "remaining_visits": 7,
            "expires_at": corrected_expiry,
            "status": SubscriptionStatus.EXPIRED,
        }
    ]
    assert len(audit.records) == 1
    assert audit.records[0]["actor_user_id"] == ACTOR_USER_ID
    assert audit.records[0]["action"] == "SUBSCRIPTION_CORRECTED"
    assert audit.records[0]["entity_id"] == SUBSCRIPTION_ID
    assert audit.records[0]["payload"] == {
        "subscription_id": SUBSCRIPTION_ID,
        "athlete_id": ATHLETE_ID,
        "source": "ADMIN_CORRECTION",
        "changes": {
            "remaining_visits": {"before": 12, "after": 7},
            "expires_at": {
                "before": (NOW + timedelta(days=20)).isoformat(),
                "after": corrected_expiry.isoformat(),
            },
            "status": {"before": "ACTIVE", "after": "EXPIRED"},
        },
    }
    assert uow.commit_calls == 1


@pytest.mark.parametrize(
    "role",
    [SystemRoleCode.TRAINER, SystemRoleCode.ATHLETE],
)
async def test_non_administrative_actor_is_forbidden(
    role: SystemRoleCode,
) -> None:
    interactor, _, subscriptions, audit, uow = make_interactor(role=role)

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(command(remaining_visits_is_set=True, remaining_visits=7))

    assert not subscriptions.updates
    assert not audit.records
    assert uow.commit_calls == 0


async def test_noop_does_not_update_audit_or_commit() -> None:
    interactor, _, subscriptions, audit, uow = make_interactor()

    result = await interactor(
        command(
            remaining_visits_is_set=True,
            remaining_visits=12,
            expires_at=NOW + timedelta(days=20),
            status=SubscriptionStatus.ACTIVE,
        )
    )

    assert result.outcome is CorrectSubscriptionOutcome.NO_CHANGES
    assert not subscriptions.updates
    assert not audit.records
    assert uow.commit_calls == 0


@pytest.mark.parametrize("remaining", [-1, True])
async def test_invalid_limited_remaining_is_rejected(remaining: object) -> None:
    interactor, _, subscriptions, audit, uow = make_interactor()

    with pytest.raises(InvalidRemainingVisitsError):
        await interactor(
            command(
                remaining_visits_is_set=True,
                remaining_visits=remaining,  # type: ignore[arg-type]
            )
        )

    assert not subscriptions.updates
    assert not audit.records
    assert uow.commit_calls == 0


async def test_limited_remaining_cannot_be_null() -> None:
    interactor, _, subscriptions, audit, _ = make_interactor()

    with pytest.raises(LimitedSubscriptionRemainingVisitsRequiredError):
        await interactor(
            command(remaining_visits_is_set=True, remaining_visits=None)
        )

    assert not subscriptions.updates
    assert not audit.records


async def test_unlimited_remaining_cannot_be_changed_to_integer() -> None:
    interactor, _, subscriptions, audit, _ = make_interactor(unlimited=True)

    with pytest.raises(UnlimitedSubscriptionRemainingVisitsForbiddenError):
        await interactor(
            command(remaining_visits_is_set=True, remaining_visits=5)
        )

    assert not subscriptions.updates
    assert not audit.records


async def test_unlimited_expiry_and_status_can_be_corrected() -> None:
    interactor, _, subscriptions, audit, uow = make_interactor(unlimited=True)

    result = await interactor(
        command(
            expires_at=NOW + timedelta(days=2),
            status=SubscriptionStatus.CANCELLED,
        )
    )

    assert result.outcome is CorrectSubscriptionOutcome.CORRECTED
    assert subscriptions.updates[0]["remaining_visits"] is None
    assert len(audit.records) == 1
    assert uow.commit_calls == 1


async def test_naive_expiration_is_rejected() -> None:
    interactor, _, subscriptions, audit, _ = make_interactor()

    with pytest.raises(InvalidSubscriptionExpirationError):
        await interactor(command(expires_at=datetime(2026, 9, 18, 15)))

    assert not subscriptions.updates
    assert not audit.records


async def test_ownership_mismatch_is_rejected() -> None:
    interactor, _, subscriptions, audit, _ = make_interactor(
        current=subscription(athlete_id=ATHLETE_ID + 1)
    )

    with pytest.raises(SubscriptionNotFoundError):
        await interactor(command())

    assert not subscriptions.updates
    assert not audit.records


async def test_newer_subscription_causes_stale_conflict() -> None:
    interactor, _, subscriptions, audit, uow = make_interactor(latest_id=999)

    with pytest.raises(LatestSubscriptionChangedError):
        await interactor(command(remaining_visits_is_set=True, remaining_visits=7))

    assert not subscriptions.updates
    assert not audit.records
    assert uow.commit_calls == 0


async def test_active_check_excludes_corrected_subscription() -> None:
    interactor, _, subscriptions, _, _ = make_interactor()

    await interactor(command(remaining_visits_is_set=True, remaining_visits=7))

    assert subscriptions.other_active_checks == [
        (ATHLETE_ID, SUBSCRIPTION_ID)
    ]


async def test_other_active_subscription_causes_conflict() -> None:
    target = subscription(status=SubscriptionStatus.EXPIRED)
    other = Subscription(
        id=999,
        athlete_id=ATHLETE_ID,
        group_id=50,
        plan_id=PLAN_ID,
        activated_by_user_id=ACTOR_USER_ID,
        activated_at=NOW,
        starts_at=NOW,
        expires_at=NOW + timedelta(days=20),
        activation_price=Decimal("5000"),
        remaining_visits=8,
        status=SubscriptionStatus.ACTIVE,
    )
    interactor, _, subscriptions, audit, uow = make_interactor(
        current=target,
        other_active=other,
    )

    with pytest.raises(ActiveSubscriptionAlreadyExistsError):
        await interactor(command(status=SubscriptionStatus.ACTIVE))

    assert subscriptions.other_active_checks == [(ATHLETE_ID, SUBSCRIPTION_ID)]
    assert not subscriptions.updates
    assert not audit.records
    assert uow.commit_calls == 0


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED),
        (SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED),
        (SubscriptionStatus.EXPIRED, SubscriptionStatus.ACTIVE),
        (SubscriptionStatus.CANCELLED, SubscriptionStatus.ACTIVE),
    ],
)
async def test_existing_status_transitions_are_allowed(
    before: SubscriptionStatus,
    after: SubscriptionStatus,
) -> None:
    interactor, _, subscriptions, audit, _ = make_interactor(
        current=subscription(status=before)
    )

    await interactor(command(status=after))

    assert subscriptions.updates[0]["status"] is after
    assert audit.records[0]["action"] == "SUBSCRIPTION_CORRECTED"
    assert audit.records[0]["payload"] != "SUBSCRIPTION_EXPIRED"


async def test_audit_failure_prevents_commit() -> None:
    error = RuntimeError("audit failed")
    interactor, _, subscriptions, audit, uow = make_interactor(
        audit_error=error
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await interactor(command(remaining_visits_is_set=True, remaining_visits=7))

    assert len(subscriptions.updates) == 1
    assert not audit.records
    assert uow.commit_calls == 0
    assert uow.exit_exception is RuntimeError
