from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.athlete_notifications import AthleteNotificationCandidate
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.athlete_notifications import (
    SqlAlchemyAthleteNotificationReader,
)
from infrastructure.database.models import (
    AthleteModel,
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

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


async def add_user(session: AsyncSession, suffix: str) -> UserModel:
    user = UserModel(
        telegram_id=700_000_000 + uuid4().int % 200_000_000,
        username=f"athlete_notify_{suffix}",
        first_name="User",
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
        code=f"ATH_NOTIFY_{suffix}",
        name=f"Кикбоксинг {suffix}",
        short_name=None,
        is_active=True,
    )
    group_name = GroupNameModel(name=f"Группа {suffix}")
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
    is_active: bool = True,
) -> SubscriptionPlanModel:
    unlimited = scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS
    plan = SubscriptionPlanModel(
        code=f"ATH_PLAN_{suffix}",
        name=f"Plan {suffix}",
        visit_limit=None if unlimited else 8,
        duration_months=1,
        price=Decimal("4000"),
        is_unlimited=unlimited,
        access_scope=scope,
        required_group_type=None,
        is_active=is_active,
    )
    session.add(plan)
    await session.flush()
    return plan


async def add_athlete(
    session: AsyncSession,
    *,
    suffix: str,
    plan: SubscriptionPlanModel,
    activated_by_user_id: int,
    group_id: int | None,
    linked: bool = True,
    starts_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=1),
    remaining_visits: int | None = 8,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> AthleteModel:
    user = await add_user(session, suffix) if linked else None
    athlete = AthleteModel(
        user_id=user.id if user is not None else None,
        first_name="Athlete",
        last_name=suffix,
        birth_date=date(1990, 1, 1),
        phone=None,
        is_active=True,
    )
    session.add(athlete)
    await session.flush()
    session.add(
        SubscriptionModel(
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
    )
    await session.flush()
    return athlete


async def test_due_window_is_exact_ten_minutes_and_cancelled_is_excluded(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, f"trainer_{suffix}")
    group = await add_group(
        db_session,
        suffix=suffix,
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    plan = await add_plan(
        db_session,
        suffix=suffix,
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
    )
    athlete = await add_athlete(
        db_session,
        suffix=suffix,
        plan=plan,
        activated_by_user_id=trainer.id,
        group_id=group.id,
    )
    starts = [
        NOW + timedelta(hours=2, seconds=1),
        NOW + timedelta(hours=2),
        NOW + timedelta(hours=1, minutes=55),
        NOW + timedelta(hours=1, minutes=50, seconds=1),
        NOW + timedelta(hours=1, minutes=50),
    ]
    sessions = [
        await add_session(
            db_session,
            group_id=group.id,
            trainer_id=trainer.id,
            starts_at=start,
        )
        for start in starts
    ]
    await add_session(
        db_session,
        group_id=group.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(hours=1, minutes=58),
        status=TrainingSessionStatus.CANCELLED,
    )

    found = await SqlAlchemyAthleteNotificationReader(
        db_session
    ).find_due_candidates(
        reference_now=NOW,
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW - timedelta(minutes=10),
    )

    assert found == tuple(
        AthleteNotificationCandidate(item.id, athlete.id)
        for item in reversed(sessions[1:4])
    )


async def test_recipient_matrix_excludes_unlimited_and_preserves_read_only_state(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, f"trainer_{suffix}")
    regular = await add_group(
        db_session,
        suffix=f"reg_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    mini = await add_group(
        db_session,
        suffix=f"mini_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.MINI,
    )
    other = await add_group(
        db_session,
        suffix=f"other_{suffix}",
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    specific = await add_plan(
        db_session,
        suffix=f"specific_{suffix}",
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
    )
    inactive_specific = await add_plan(
        db_session,
        suffix=f"inactive_{suffix}",
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        is_active=False,
    )
    unlimited = await add_plan(
        db_session,
        suffix=f"unlimited_{suffix}",
        scope=SubscriptionAccessScope.ALL_REGULAR_GROUPS,
    )
    regular_session = await add_session(
        db_session,
        group_id=regular.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(hours=2),
    )
    mini_session = await add_session(
        db_session,
        group_id=mini.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(hours=2),
    )

    eligible_regular = await add_athlete(
        db_session, suffix=f"ok_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id, remaining_visits=5,
    )
    eligible_one = await add_athlete(
        db_session, suffix=f"one_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id, remaining_visits=1,
    )
    eligible_inactive_plan = await add_athlete(
        db_session, suffix=f"inactive_plan_{suffix}", plan=inactive_specific,
        activated_by_user_id=trainer.id, group_id=regular.id,
    )
    eligible_mini = await add_athlete(
        db_session, suffix=f"mini_ok_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=mini.id,
    )
    await add_athlete(
        db_session, suffix=f"other_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=other.id,
    )
    elapsed = await add_athlete(
        db_session, suffix=f"elapsed_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id,
        expires_at=NOW,
    )
    zero = await add_athlete(
        db_session, suffix=f"zero_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id, remaining_visits=0,
    )
    await add_athlete(
        db_session, suffix=f"future_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id,
        starts_at=NOW + timedelta(minutes=1),
    )
    await add_athlete(
        db_session, suffix=f"cancelled_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id,
        status=SubscriptionStatus.CANCELLED,
    )
    await add_athlete(
        db_session, suffix=f"manual_{suffix}", plan=specific,
        activated_by_user_id=trainer.id, group_id=regular.id, linked=False,
    )
    await add_athlete(
        db_session, suffix=f"unlimited_reg_{suffix}", plan=unlimited,
        activated_by_user_id=trainer.id, group_id=None, remaining_visits=None,
    )
    await add_athlete(
        db_session, suffix=f"unlimited_mini_{suffix}", plan=unlimited,
        activated_by_user_id=trainer.id, group_id=None, remaining_visits=None,
    )

    found = await SqlAlchemyAthleteNotificationReader(
        db_session
    ).find_due_candidates(
        reference_now=NOW,
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW - timedelta(minutes=10),
    )

    assert set(found) == {
        AthleteNotificationCandidate(regular_session.id, eligible_regular.id),
        AthleteNotificationCandidate(regular_session.id, eligible_one.id),
        AthleteNotificationCandidate(
            regular_session.id, eligible_inactive_plan.id
        ),
        AthleteNotificationCandidate(mini_session.id, eligible_mini.id),
    }
    elapsed_subscription = await db_session.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.athlete_id == elapsed.id
        )
    )
    zero_subscription = await db_session.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.athlete_id == zero.id
        )
    )
    assert elapsed_subscription is not None
    assert zero_subscription is not None
    assert elapsed_subscription.status is SubscriptionStatus.ACTIVE
    assert zero_subscription.status is SubscriptionStatus.ACTIVE
    assert zero_subscription.remaining_visits == 0


async def test_notification_status_and_stale_pending_control_discovery(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, f"trainer_{suffix}")
    group = await add_group(
        db_session, suffix=suffix, trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    plan = await add_plan(
        db_session, suffix=suffix,
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
    )
    athlete = await add_athlete(
        db_session, suffix=suffix, plan=plan,
        activated_by_user_id=trainer.id, group_id=group.id,
    )
    training_session = await add_session(
        db_session, group_id=group.id, trainer_id=trainer.id,
        starts_at=NOW + timedelta(hours=2),
    )
    user_id = athlete.user_id
    assert user_id is not None
    notification = NotificationModel(
        recipient_user_id=user_id,
        training_session_id=training_session.id,
        type="ATHLETE_SESSION_MINUS_2H",
        scheduled_at=NOW,
        sent_at=None,
        status=NotificationStatus.PENDING,
        idempotency_key=(
            f"ATHLETE_SESSION_MINUS_2H:{training_session.id}:{athlete.id}"
        ),
        attempts=1,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(notification)
    await db_session.flush()
    reader = SqlAlchemyAthleteNotificationReader(db_session)

    fresh = await reader.find_due_candidates(
        reference_now=NOW,
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW - timedelta(minutes=10),
    )
    notification.updated_at = NOW - timedelta(minutes=11)
    await db_session.flush()
    stale = await reader.find_due_candidates(
        reference_now=NOW + timedelta(minutes=30),
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW + timedelta(minutes=20),
    )

    assert fresh == ()
    assert stale == (
        AthleteNotificationCandidate(training_session.id, athlete.id),
    )


async def test_subscription_issued_inside_grace_is_due_but_after_grace_is_not(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    trainer = await add_user(db_session, f"trainer_{suffix}")
    group = await add_group(
        db_session,
        suffix=suffix,
        trainer_id=trainer.id,
        group_type=TrainingGroupType.REGULAR,
    )
    plan = await add_plan(
        db_session,
        suffix=suffix,
        scope=SubscriptionAccessScope.SPECIFIC_GROUP,
    )
    athlete = await add_athlete(
        db_session,
        suffix=suffix,
        plan=plan,
        activated_by_user_id=trainer.id,
        group_id=group.id,
        starts_at=NOW + timedelta(minutes=5),
    )
    training_session = await add_session(
        db_session,
        group_id=group.id,
        trainer_id=trainer.id,
        starts_at=NOW + timedelta(hours=2),
    )
    reader = SqlAlchemyAthleteNotificationReader(db_session)

    inside_grace = await reader.find_due_candidates(
        reference_now=NOW + timedelta(minutes=5),
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW - timedelta(minutes=5),
    )
    after_grace = await reader.find_due_candidates(
        reference_now=NOW + timedelta(minutes=30),
        notify_before_seconds=7200,
        grace_window_seconds=600,
        stale_pending_before=NOW + timedelta(minutes=20),
    )

    assert inside_grace == (
        AthleteNotificationCandidate(training_session.id, athlete.id),
    )
    assert after_grace == ()
