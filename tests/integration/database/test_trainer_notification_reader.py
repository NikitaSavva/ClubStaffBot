from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.attendance import AttendanceSource, AttendanceStatus
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.subscriptions import (
    SubscriptionAccessScope,
    SubscriptionStatus,
)
from infrastructure.database.models import (
    AthleteModel,
    AttendanceModel,
    GroupNameModel,
    NotificationModel,
    NotificationStatus,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.trainer_notifications import (
    SqlAlchemyTrainerNotificationReader,
)

NOW = datetime(2026, 9, 2, 15, 55, tzinfo=UTC)


async def add_user(session: AsyncSession, suffix: str) -> UserModel:
    user = UserModel(
        telegram_id=700_000_000 + uuid4().int % 200_000_000,
        username=f"notify_{suffix}",
        first_name="Trainer",
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    return user


async def add_group(
    session: AsyncSession,
    *,
    suffix: str,
    trainer_id: int,
    group_type: TrainingGroupType,
) -> TrainingGroupModel:
    direction = SportDirectionModel(
        code=f"NOTIFY_{suffix}",
        name=f"Кикбоксинг {suffix}",
        short_name=None,
        is_active=True,
    )
    group_name = GroupNameModel(name=f"Взрослые {suffix}")
    session.add_all([direction, group_name])
    await session.flush()
    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=trainer_id,
        name_id=group_name.id,
        group_type=group_type,
        is_active=True,
    )
    session.add(group)
    await session.flush()
    return group


async def add_session(
    session: AsyncSession,
    *,
    group_id: int,
    trainer_id: int,
    starts_at: datetime,
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
) -> TrainingSessionModel:
    training_session = TrainingSessionModel(
        schedule_rule_id=None,
        group_id=group_id,
        trainer_id=trainer_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1, minutes=30),
        status=status,
        is_overridden=False,
    )
    session.add(training_session)
    await session.flush()
    return training_session


async def add_plan(
    session: AsyncSession,
    *,
    suffix: str,
    scope: SubscriptionAccessScope,
    group_type: TrainingGroupType | None,
    is_active: bool = True,
) -> SubscriptionPlanModel:
    unlimited = scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS
    plan = SubscriptionPlanModel(
        code=f"PLAN_{suffix}",
        name=f"Plan {suffix}",
        visit_limit=None if unlimited else 8,
        duration_months=1,
        price=Decimal("4000"),
        is_unlimited=unlimited,
        access_scope=scope,
        required_group_type=group_type,
        is_active=is_active,
    )
    session.add(plan)
    await session.flush()
    return plan


async def add_subscription(
    session: AsyncSession,
    *,
    suffix: str,
    plan: SubscriptionPlanModel,
    activated_by_user_id: int,
    group_id: int | None,
    starts_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=1),
    remaining_visits: int | None = 8,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> tuple[AthleteModel, SubscriptionModel]:
    athlete = AthleteModel(
        user_id=None,
        first_name="Athlete",
        last_name=suffix,
        birth_date=date(1990, 1, 1),
        phone=None,
        is_active=True,
    )
    session.add(athlete)
    await session.flush()
    subscription = SubscriptionModel(
        athlete_id=athlete.id,
        group_id=group_id,
        plan_id=plan.id,
        activated_by_user_id=activated_by_user_id,
        activated_at=NOW - timedelta(days=1),
        starts_at=starts_at,
        expires_at=expires_at,
        activation_price=plan.price,
        remaining_visits=remaining_visits,
        status=status,
    )
    session.add(subscription)
    await session.flush()
    return athlete, subscription


async def test_due_window_delayed_polling_status_and_pending_lease(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, suffix)
    group = await add_group(
        db_session,
        suffix=suffix,
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    starts = (
        NOW + timedelta(minutes=6),
        NOW + timedelta(minutes=5),
        NOW + timedelta(minutes=4),
        NOW + timedelta(seconds=1),
        NOW,
        NOW - timedelta(seconds=1),
    )
    sessions = [
        await add_session(
            db_session,
            group_id=group.id,
            trainer_id=trainer.id,
            starts_at=start,
        )
        for start in starts
    ]
    cancelled = await add_session(
        db_session,
        group_id=group.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(minutes=3),
        status=TrainingSessionStatus.CANCELLED,
    )
    del cancelled
    db_session.add(
        NotificationModel(
            recipient_user_id=trainer.id,
            training_session_id=sessions[1].id,
            type="TRAINER_SESSION_MINUS_5",
            scheduled_at=NOW,
            sent_at=None,
            status=NotificationStatus.PENDING,
            idempotency_key=(
                f"TRAINER_SESSION_MINUS_5:{sessions[1].id}"
            ),
            attempts=1,
            created_at=NOW - timedelta(minutes=1),
            updated_at=NOW - timedelta(minutes=1),
        )
    )
    await db_session.flush()
    reader = SqlAlchemyTrainerNotificationReader(db_session)

    found = await reader.find_due_session_ids(
        reference_now=NOW,
        notify_before_seconds=300,
        stale_pending_before=NOW - timedelta(minutes=10),
    )

    assert found == (sessions[3].id, sessions[2].id)

    notification = await db_session.scalar(
        select(NotificationModel).where(
            NotificationModel.training_session_id == sessions[1].id
        )
    )
    assert notification is not None
    notification.updated_at = NOW - timedelta(minutes=11)
    db_session.add(
        NotificationModel(
            recipient_user_id=trainer.id,
            training_session_id=sessions[4].id,
            type="TRAINER_SESSION_MINUS_5",
            scheduled_at=NOW - timedelta(minutes=5),
            sent_at=None,
            status=NotificationStatus.PENDING,
            idempotency_key=(
                f"TRAINER_SESSION_MINUS_5:{sessions[4].id}"
            ),
            attempts=1,
            created_at=NOW - timedelta(minutes=11),
            updated_at=NOW - timedelta(minutes=11),
        )
    )
    await db_session.flush()

    found_after_stale = await reader.find_due_session_ids(
        reference_now=NOW,
        notify_before_seconds=300,
        stale_pending_before=NOW - timedelta(minutes=10),
    )

    assert found_after_stale == (
        sessions[4].id,
        sessions[3].id,
        sessions[2].id,
        sessions[1].id,
    )


async def test_expected_and_confirmed_counts_use_current_entitlement_snapshot(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, suffix)
    regular = await add_group(
        db_session,
        suffix=f"REG_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    mini = await add_group(
        db_session,
        suffix=f"MINI_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.MINI,
    )
    other = await add_group(
        db_session,
        suffix=f"OTHER_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    session = await add_session(
        db_session,
        group_id=regular.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(minutes=5),
    )
    other_session = await add_session(
        db_session,
        group_id=other.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(minutes=5),
    )
    specific_regular = await add_plan(
        db_session,
        suffix=f"SR_{suffix}",
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        group_type=TrainingGroupType.REGULAR,
    )
    specific_mini = await add_plan(
        db_session,
        suffix=f"SM_{suffix}",
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        group_type=TrainingGroupType.MINI,
    )
    unlimited_inactive = await add_plan(
        db_session,
        suffix=f"UN_{suffix}",
        scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
        group_type=None,
        is_active=False,
    )

    counted, counted_subscription = await add_subscription(
        db_session,
        suffix=f"counted_{suffix}",
        plan=specific_regular,
        activated_by_user_id=trainer.id,
        group_id=regular.id,
        remaining_visits=1,
    )
    await add_subscription(
        db_session,
        suffix=f"other_{suffix}",
        plan=specific_regular,
        activated_by_user_id=trainer.id,
        group_id=other.id,
    )
    await add_subscription(
        db_session,
        suffix=f"zero_{suffix}",
        plan=specific_regular,
        activated_by_user_id=trainer.id,
        group_id=regular.id,
        remaining_visits=0,
    )
    _, elapsed_subscription = await add_subscription(
        db_session,
        suffix=f"elapsed_{suffix}",
        plan=specific_regular,
        activated_by_user_id=trainer.id,
        group_id=regular.id,
        expires_at=NOW,
    )
    await add_subscription(
        db_session,
        suffix=f"future_{suffix}",
        plan=specific_regular,
        activated_by_user_id=trainer.id,
        group_id=regular.id,
        starts_at=NOW + timedelta(seconds=1),
    )
    unlimited_athlete, unlimited_subscription = await add_subscription(
        db_session,
        suffix=f"unlimited_{suffix}",
        plan=unlimited_inactive,
        activated_by_user_id=trainer.id,
        group_id=None,
        remaining_visits=None,
    )
    mini_athlete, mini_subscription = await add_subscription(
        db_session,
        suffix=f"mini_{suffix}",
        plan=specific_mini,
        activated_by_user_id=trainer.id,
        group_id=mini.id,
        remaining_visits=3,
    )
    reader = SqlAlchemyTrainerNotificationReader(db_session)

    regular_count = await reader.count_expected(
        training_group_id=regular.id,
        group_is_regular=True,
        reference_now=NOW,
    )
    mini_count = await reader.count_expected(
        training_group_id=mini.id,
        group_is_regular=False,
        reference_now=NOW,
    )

    assert regular_count == 2
    assert mini_count == 1
    assert elapsed_subscription.status is SubscriptionStatus.ACTIVE
    assert unlimited_athlete.user_id is None

    db_session.add_all(
        [
            AttendanceModel(
                training_session_id=session.id,
                athlete_id=counted.id,
                subscription_id=counted_subscription.id,
                confirmed_by_user_id=trainer.id,
                source=AttendanceSource.MANUAL,
                status=AttendanceStatus.CONFIRMED,
                confirmed_at=NOW,
            ),
            AttendanceModel(
                training_session_id=session.id,
                athlete_id=unlimited_athlete.id,
                subscription_id=unlimited_subscription.id,
                confirmed_by_user_id=trainer.id,
                source=AttendanceSource.QR,
                status=AttendanceStatus.CANCELLED,
                confirmed_at=NOW,
            ),
            AttendanceModel(
                training_session_id=other_session.id,
                athlete_id=mini_athlete.id,
                subscription_id=mini_subscription.id,
                confirmed_by_user_id=trainer.id,
                source=AttendanceSource.MANUAL,
                status=AttendanceStatus.CONFIRMED,
                confirmed_at=NOW,
            ),
        ]
    )
    await db_session.flush()

    assert await reader.count_confirmed(session.id) == 1


async def test_session_projection_uses_materialized_trainer_start_and_end(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    snapshot_trainer = await add_user(db_session, f"SNAP_{suffix}")
    current_group_trainer = await add_user(db_session, f"GROUP_{suffix}")
    group = await add_group(
        db_session,
        suffix=suffix,
        trainer_id=current_group_trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    starts_at = NOW + timedelta(minutes=4)
    training_session = await add_session(
        db_session,
        group_id=group.id,
        trainer_id=snapshot_trainer.id,
        starts_at=starts_at,
    )

    projected = await SqlAlchemyTrainerNotificationReader(
        db_session
    ).get_session(training_session.id)

    assert projected is not None
    assert projected.trainer_id == snapshot_trainer.id
    assert projected.trainer_telegram_id == snapshot_trainer.telegram_id
    assert projected.starts_at == starts_at
    assert projected.ends_at == starts_at + timedelta(hours=1, minutes=30)
