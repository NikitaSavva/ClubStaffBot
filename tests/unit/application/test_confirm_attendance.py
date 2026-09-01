from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from application.attendance import (
    AttendanceAlreadyExistsError,
    AttendanceSessionCandidate,
    ConfirmAttendanceCommand,
    ConfirmAttendanceInteractor,
    ConfirmAttendanceOutcome,
)
from application.identity.errors import AdministratorPermissionRequiredError
from domain.attendance import Attendance, AttendanceSource
from domain.club import (
    TrainingGroupType,
    TrainingSessionStatus,
)
from domain.identity import Athlete, SystemRoleCode, User
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionPlan,
    SubscriptionStatus,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
ACTOR_TELEGRAM_ID = 10_001
ACTOR_USER_ID = 10
ATHLETE_ID = 20
ATHLETE_PUBLIC_ID = UUID("12345678-1234-4678-9234-567812345678")
SUBSCRIPTION_ID = 30
PLAN_ID = 40
GROUP_ID = 50
SESSION_ID = 60


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeUnitOfWork(AbstractAsyncContextManager["FakeUnitOfWork"]):
    def __init__(self) -> None:
        self.commits = 0
        self.flushes = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1


class FakeUsers:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id != ACTOR_TELEGRAM_ID:
            return None
        return User(
            id=ACTOR_USER_ID,
            telegram_id=telegram_id,
            username="admin",
            first_name="Admin",
            last_name=None,
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )


class FakeRoles:
    def __init__(self, roles: tuple[SystemRoleCode, ...]) -> None:
        self.roles = roles

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        return self.roles if user_id == ACTOR_USER_ID else ()


class FakeAthletes:
    def __init__(self) -> None:
        self.locked_public_ids: list[UUID] = []

    async def get_by_public_id_for_update(
        self,
        athlete_public_id: UUID,
    ) -> Athlete | None:
        self.locked_public_ids.append(athlete_public_id)
        return Athlete(
            id=ATHLETE_ID,
            athlete_public_id=ATHLETE_PUBLIC_ID,
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            birth_date=date(1991, 12, 27),
            phone=None,
            is_active=True,
        )


class FakeSubscriptions:
    def __init__(self, subscription: Subscription | None) -> None:
        self.subscription = subscription
        self.locked_athlete_ids: list[int] = []
        self.expired_ids: list[int] = []
        self.attendance_updates: list[tuple[int, int, int, SubscriptionStatus]] = []

    async def get_active_by_athlete_for_update(
        self,
        athlete_id: int,
    ) -> Subscription | None:
        self.locked_athlete_ids.append(athlete_id)
        return self.subscription

    async def mark_expired(self, subscription_id: int) -> bool:
        if self.subscription is None or self.subscription.id != subscription_id:
            return False
        self.expired_ids.append(subscription_id)
        self.subscription = replace(
            self.subscription,
            status=SubscriptionStatus.EXPIRED,
        )
        return True

    async def update_attendance_state(
        self,
        *,
        subscription_id: int,
        expected_remaining_visits: int,
        remaining_visits: int,
        status: SubscriptionStatus,
    ) -> bool:
        self.attendance_updates.append(
            (
                subscription_id,
                expected_remaining_visits,
                remaining_visits,
                status,
            )
        )
        if self.subscription is None:
            return False
        self.subscription = replace(
            self.subscription,
            remaining_visits=remaining_visits,
            status=status,
        )
        return True


class FakePlans:
    def __init__(self, plan: SubscriptionPlan) -> None:
        self.plan = plan

    async def get_by_id(self, plan_id: int) -> SubscriptionPlan | None:
        return self.plan if plan_id == self.plan.id else None


class FakeSessions:
    def __init__(
        self,
        *,
        group: tuple[AttendanceSessionCandidate, ...] = (),
        regular: tuple[AttendanceSessionCandidate, ...] = (),
        selected: AttendanceSessionCandidate | None = None,
    ) -> None:
        self.group = group
        self.regular = regular
        self.selected = selected
        self.group_windows: list[tuple[int, datetime, datetime]] = []

    async def list_by_group_for_update(
        self,
        *,
        training_group_id: int,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]:
        self.group_windows.append(
            (training_group_id, starts_at_from, starts_at_to)
        )
        return self.group

    async def list_regular(
        self,
        *,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]:
        return self.regular

    async def get_by_id_for_update(
        self,
        training_session_id: int,
    ) -> AttendanceSessionCandidate | None:
        if self.selected is None or self.selected.id != training_session_id:
            return None
        return self.selected


class FakeAttendances:
    def __init__(
        self,
        *,
        duplicate: bool = False,
        insert_error: Exception | None = None,
    ) -> None:
        self.duplicate = duplicate
        self.insert_error = insert_error
        self.added: list[Attendance] = []

    async def exists(
        self,
        *,
        training_session_id: int,
        athlete_id: int,
    ) -> bool:
        return self.duplicate

    async def add(self, attendance: Attendance) -> int:
        if self.insert_error is not None:
            raise self.insert_error
        self.added.append(attendance)
        return 70


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def add(self, **event: object) -> None:
        self.events.append(event)


def subscription(
    *,
    remaining_visits: int | None = 8,
    starts_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=10),
) -> Subscription:
    return Subscription(
        id=SUBSCRIPTION_ID,
        athlete_id=ATHLETE_ID,
        group_id=GROUP_ID if remaining_visits is not None else None,
        plan_id=PLAN_ID,
        activated_by_user_id=ACTOR_USER_ID,
        activated_at=NOW - timedelta(days=1),
        starts_at=starts_at,
        expires_at=expires_at,
        activation_price=Decimal("5000"),
        remaining_visits=remaining_visits,
        status=SubscriptionStatus.ACTIVE,
    )


def plan(
    scope: SubscriptionAccessScope = SubscriptionAccessScope.SPECIFIC_GROUP,
    *,
    is_active: bool = True,
) -> SubscriptionPlan:
    return SubscriptionPlan(
        id=PLAN_ID,
        code="PLAN",
        name="Абонемент",
        visit_limit=(8 if scope is SubscriptionAccessScope.SPECIFIC_GROUP else None),
        duration_months=1,
        price=Decimal("5000"),
        is_unlimited=scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS,
        access_scope=scope,
        required_group_type=(
            TrainingGroupType.REGULAR
            if scope is SubscriptionAccessScope.SPECIFIC_GROUP
            else None
        ),
        is_active=is_active,
    )


def candidate(
    *,
    session_id: int = SESSION_ID,
    starts_at: datetime = NOW + timedelta(hours=4),
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
    group_type: TrainingGroupType = TrainingGroupType.REGULAR,
) -> AttendanceSessionCandidate:
    return AttendanceSessionCandidate(
        id=session_id,
        training_group_id=GROUP_ID,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1, minutes=30),
        status=status,
        group_type=group_type,
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые",
    )


def make_interactor(
    *,
    current_subscription: Subscription | None = None,
    current_plan: SubscriptionPlan | None = None,
    sessions: FakeSessions | None = None,
    attendances: FakeAttendances | None = None,
    roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.ADMINISTRATOR,),
) -> tuple[
    ConfirmAttendanceInteractor,
    FakeSubscriptions,
    FakeAttendances,
    FakeAudit,
    FakeUnitOfWork,
    FakeSessions,
]:
    subscriptions = FakeSubscriptions(
        subscription() if current_subscription is None else current_subscription
    )
    attendance_repository = attendances or FakeAttendances()
    audit = FakeAudit()
    uow = FakeUnitOfWork()
    session_repository = sessions or FakeSessions(group=(candidate(),))
    interactor = ConfirmAttendanceInteractor(
        user_repository=FakeUsers(),  # type: ignore[arg-type]
        athlete_repository=FakeAthletes(),  # type: ignore[arg-type]
        role_repository=FakeRoles(roles),  # type: ignore[arg-type]
        subscription_repository=subscriptions,  # type: ignore[arg-type]
        subscription_plan_repository=FakePlans(current_plan or plan()),
        training_session_repository=session_repository,
        attendance_repository=attendance_repository,
        audit_log_repository=audit,  # type: ignore[arg-type]
        unit_of_work=uow,
        clock=FrozenClock(),
        club_timezone=CLUB_TIMEZONE,
    )
    return (
        interactor,
        subscriptions,
        attendance_repository,
        audit,
        uow,
        session_repository,
    )


def command(
    *,
    source: AttendanceSource = AttendanceSource.QR,
    training_session_id: int | None = None,
) -> ConfirmAttendanceCommand:
    return ConfirmAttendanceCommand(
        actor_telegram_id=ACTOR_TELEGRAM_ID,
        athlete_public_id=ATHLETE_PUBLIC_ID,
        source=source,
        training_session_id=training_session_id,
    )


@pytest.mark.parametrize(
    ("current", "expected", "reason"),
    [
        (
            subscription(expires_at=NOW),
            ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED,
            "TIME_ELAPSED",
        ),
        (
            subscription(remaining_visits=0),
            ConfirmAttendanceOutcome.VISITS_EXHAUSTED,
            "VISITS_EXHAUSTED",
        ),
    ],
)
async def test_rejected_expiration_is_committed_with_one_system_audit(
    current: Subscription,
    expected: ConfirmAttendanceOutcome,
    reason: str,
) -> None:
    interactor, subscriptions, attendances, audit, uow, _ = make_interactor(
        current_subscription=current
    )

    result = await interactor(command())

    assert result.outcome is expected
    assert subscriptions.subscription is not None
    assert subscriptions.subscription.status is SubscriptionStatus.EXPIRED
    assert attendances.added == []
    assert uow.commits == 1
    assert [event["action"] for event in audit.events] == [
        "SUBSCRIPTION_EXPIRED"
    ]
    assert audit.events[0]["actor_user_id"] is None
    assert audit.events[0]["payload"]["reason"] == reason  # type: ignore[index]


async def test_limited_attendance_decrements_persisted_counter() -> None:
    interactor, subscriptions, attendances, audit, uow, _ = make_interactor(
        current_plan=plan(is_active=False)
    )

    result = await interactor(command(source=AttendanceSource.MANUAL))

    assert result.outcome is ConfirmAttendanceOutcome.CONFIRMED
    assert result.remaining_visits == 7
    assert result.subscription_finished is False
    assert subscriptions.attendance_updates == [
        (SUBSCRIPTION_ID, 8, 7, SubscriptionStatus.ACTIVE)
    ]
    assert attendances.added[0].source is AttendanceSource.MANUAL
    assert attendances.added[0].status.value == "CONFIRMED"
    assert [event["action"] for event in audit.events] == [
        "ATTENDANCE_CREATED"
    ]
    assert uow.commits == 1


async def test_last_visit_succeeds_and_expires_in_one_commit() -> None:
    interactor, subscriptions, attendances, audit, uow, _ = make_interactor(
        current_subscription=subscription(remaining_visits=1)
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.CONFIRMED
    assert result.remaining_visits == 0
    assert result.subscription_finished is True
    assert len(attendances.added) == 1
    assert subscriptions.subscription is not None
    assert subscriptions.subscription.status is SubscriptionStatus.EXPIRED
    assert [event["action"] for event in audit.events] == [
        "ATTENDANCE_CREATED",
        "SUBSCRIPTION_EXPIRED",
    ]
    assert audit.events[1]["actor_user_id"] is None
    assert audit.events[1]["payload"]["reason"] == "VISITS_EXHAUSTED"  # type: ignore[index]
    assert uow.commits == 1


async def test_unlimited_first_request_lists_regular_sessions_including_cancelled() -> None:
    morning = candidate(session_id=1, starts_at=NOW - timedelta(hours=2))
    cancelled = candidate(
        session_id=2,
        starts_at=NOW + timedelta(hours=2),
        status=TrainingSessionStatus.CANCELLED,
    )
    sessions = FakeSessions(regular=(morning, cancelled))
    interactor, subscriptions, attendances, _, uow, _ = make_interactor(
        current_subscription=subscription(remaining_visits=None),
        current_plan=plan(SubscriptionAccessScope.ALL_REGULAR_GROUPS),
        sessions=sessions,
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED
    assert [item.training_session_id for item in result.sessions] == [1, 2]
    assert [item.selectable for item in result.sessions] == [True, False]
    assert subscriptions.attendance_updates == []
    assert attendances.added == []
    assert uow.commits == 0


async def test_unlimited_without_sessions_returns_empty_selection_state() -> None:
    interactor, _, attendances, _, uow, _ = make_interactor(
        current_subscription=subscription(remaining_visits=None),
        current_plan=plan(SubscriptionAccessScope.ALL_REGULAR_GROUPS),
        sessions=FakeSessions(regular=()),
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED
    assert result.sessions == ()
    assert attendances.added == []
    assert uow.commits == 0


@pytest.mark.parametrize(
    "selected",
    [
        candidate(group_type=TrainingGroupType.MINI),
        candidate(starts_at=NOW - timedelta(days=1)),
    ],
)
async def test_unlimited_tampered_session_is_rejected(
    selected: AttendanceSessionCandidate,
) -> None:
    interactor, _, attendances, _, uow, _ = make_interactor(
        current_subscription=subscription(remaining_visits=None),
        current_plan=plan(SubscriptionAccessScope.ALL_REGULAR_GROUPS),
        sessions=FakeSessions(selected=selected),
    )

    result = await interactor(
        command(training_session_id=selected.id)
    )

    assert result.outcome is ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED
    assert attendances.added == []
    assert uow.commits == 0


async def test_unlimited_selected_cancelled_is_revalidated() -> None:
    selected = candidate(status=TrainingSessionStatus.CANCELLED)
    interactor, _, attendances, _, _, _ = make_interactor(
        current_subscription=subscription(remaining_visits=None),
        current_plan=plan(SubscriptionAccessScope.ALL_REGULAR_GROUPS),
        sessions=FakeSessions(selected=selected),
    )

    result = await interactor(command(training_session_id=SESSION_ID))

    assert result.outcome is ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED
    assert attendances.added == []


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        ((), ConfirmAttendanceOutcome.NO_TRAINING_SESSION),
        (
            (candidate(session_id=1), candidate(session_id=2)),
            ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS,
        ),
        (
            (candidate(status=TrainingSessionStatus.CANCELLED),),
            ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED,
        ),
    ],
)
async def test_specific_group_controlled_session_outcomes(
    candidates: tuple[AttendanceSessionCandidate, ...],
    expected: ConfirmAttendanceOutcome,
) -> None:
    interactor, subscriptions, attendances, _, uow, session_repository = (
        make_interactor(sessions=FakeSessions(group=candidates))
    )

    result = await interactor(command(training_session_id=999))

    assert result.outcome is expected
    assert attendances.added == []
    assert subscriptions.attendance_updates == []
    assert uow.commits == 0
    assert session_repository.group_windows == [
        (
            GROUP_ID,
            datetime(2026, 8, 31, 21, tzinfo=UTC),
            datetime(2026, 9, 1, 21, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize(
    "starts_at",
    [
        NOW + timedelta(hours=4),
        NOW - timedelta(minutes=30),
        NOW - timedelta(hours=5),
    ],
)
async def test_before_during_and_after_today_are_allowed(
    starts_at: datetime,
) -> None:
    interactor, _, attendances, _, _, _ = make_interactor(
        sessions=FakeSessions(group=(candidate(starts_at=starts_at),))
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.CONFIRMED
    assert len(attendances.added) == 1


async def test_past_completed_today_is_allowed() -> None:
    interactor, _, attendances, _, _, _ = make_interactor(
        sessions=FakeSessions(
            group=(
                candidate(
                    starts_at=NOW - timedelta(hours=4),
                    status=TrainingSessionStatus.COMPLETED,
                ),
            )
        )
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.CONFIRMED
    assert len(attendances.added) == 1


@pytest.mark.parametrize(
    "attendances",
    [
        FakeAttendances(duplicate=True),
        FakeAttendances(insert_error=AttendanceAlreadyExistsError()),
    ],
)
async def test_duplicate_never_decrements_or_audits(
    attendances: FakeAttendances,
) -> None:
    interactor, subscriptions, _, audit, uow, _ = make_interactor(
        attendances=attendances
    )

    result = await interactor(command())

    assert result.outcome is ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS
    assert subscriptions.attendance_updates == []
    assert audit.events == []
    assert uow.commits == 0


@pytest.mark.parametrize(
    "roles",
    [
        (SystemRoleCode.ADMINISTRATOR,),
        (SystemRoleCode.OWNER,),
        (SystemRoleCode.ADMINISTRATOR, SystemRoleCode.ATHLETE),
        (SystemRoleCode.OWNER, SystemRoleCode.TRAINER),
    ],
)
async def test_administrative_roles_are_allowed(
    roles: tuple[SystemRoleCode, ...],
) -> None:
    interactor, _, attendances, _, _, _ = make_interactor(roles=roles)
    result = await interactor(command())
    assert result.outcome is ConfirmAttendanceOutcome.CONFIRMED
    assert len(attendances.added) == 1


@pytest.mark.parametrize(
    "roles",
    [(SystemRoleCode.ATHLETE,), (SystemRoleCode.TRAINER,)],
)
async def test_non_administrative_roles_are_forbidden(
    roles: tuple[SystemRoleCode, ...],
) -> None:
    interactor, _, attendances, _, _, _ = make_interactor(roles=roles)
    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(command())
    assert attendances.added == []
