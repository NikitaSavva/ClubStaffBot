from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.identity import BotInvitePurpose
from infrastructure.database.models import (
    AthleteModel,
    AttendanceModel,
    AttendanceSource,
    AttendanceStatus,
    Base,
    BotInviteModel,
    NotificationModel,
    NotificationStatus,
    RoleModel,
    ScheduleRuleModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    SubscriptionStatus,
    TrainingGroupModel,
    TrainingGroupType,
    TrainingSessionModel,
    TrainingSessionStatus,
    UserModel,
    UserRoleModel,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
MVP_TABLES = {
    "athletes",
    "attendances",
    "audit_log",
    "bot_invites",
    "notifications",
    "roles",
    "schedule_rules",
    "sport_directions",
    "subscription_plans",
    "subscriptions",
    "training_groups",
    "training_sessions",
    "user_roles",
    "users",
}


async def add_user(session: AsyncSession, telegram_id: int) -> UserModel:
    user = UserModel(
        telegram_id=telegram_id,
        username=None,
        first_name="Test",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    return user


async def add_athlete(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    athlete_public_id: UUID | None = None,
) -> AthleteModel:
    athlete = AthleteModel(
        user_id=user_id,
        first_name="Test",
        last_name=None,
        phone=None,
        is_active=True,
    )
    if athlete_public_id is not None:
        athlete.athlete_public_id = athlete_public_id
    session.add(athlete)
    await session.flush()
    return athlete


async def add_training_group(
    session: AsyncSession,
    trainer_id: int | None,
) -> TrainingGroupModel:
    direction = SportDirectionModel(code=f"direction-{uuid4()}", name="MMA", is_active=True)
    session.add(direction)
    await session.flush()

    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=trainer_id,
        name="Morning group",
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add(group)
    await session.flush()
    return group


async def add_schedule_rule(
    session: AsyncSession,
    group_id: int,
) -> ScheduleRuleModel:
    rule = ScheduleRuleModel(
        group_id=group_id,
        weekday=1,
        start_time=time(10, 0),
        end_time=time(11, 0),
        valid_from=date(2026, 8, 1),
        valid_until=None,
        is_active=True,
    )
    session.add(rule)
    await session.flush()
    return rule


async def add_training_session(
    session: AsyncSession,
    *,
    group_id: int,
    trainer_id: int,
    schedule_rule_id: int | None,
    starts_at: datetime = NOW,
) -> TrainingSessionModel:
    training_session = TrainingSessionModel(
        schedule_rule_id=schedule_rule_id,
        group_id=group_id,
        trainer_id=trainer_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status=TrainingSessionStatus.SCHEDULED,
        is_overridden=False,
    )
    session.add(training_session)
    await session.flush()
    return training_session


async def add_subscription_plan(session: AsyncSession) -> SubscriptionPlanModel:
    plan = SubscriptionPlanModel(
        name="Eight visits",
        visit_limit=8,
        duration_days=30,
        price=Decimal("5000.00"),
        is_unlimited=False,
        is_active=True,
    )
    session.add(plan)
    await session.flush()
    return plan


async def add_subscription(
    session: AsyncSession,
    *,
    athlete_id: int,
    group_id: int,
    plan_id: int,
    activated_by_user_id: int,
    status: SubscriptionStatus,
) -> SubscriptionModel:
    subscription = SubscriptionModel(
        athlete_id=athlete_id,
        group_id=group_id,
        plan_id=plan_id,
        activated_by_user_id=activated_by_user_id,
        activated_at=NOW,
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
        activation_price=Decimal("5000.00"),
        status=status,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def add_subscription_context(
    session: AsyncSession,
) -> tuple[UserModel, AthleteModel, TrainingGroupModel, SubscriptionPlanModel]:
    actor = await add_user(session, telegram_id=1_000_000 + uuid4().int % 1_000_000)
    athlete = await add_athlete(session)
    group = await add_training_group(session, actor.id)
    plan = await add_subscription_plan(session)
    return actor, athlete, group, plan


def test_metadata_contains_exactly_the_mvp_tables() -> None:
    assert set(Base.metadata.tables) == MVP_TABLES


async def test_users_telegram_id_is_unique(db_session: AsyncSession) -> None:
    await add_user(db_session, telegram_id=1001)

    with pytest.raises(IntegrityError):
        await add_user(db_session, telegram_id=1001)


async def test_athlete_public_id_is_unique(db_session: AsyncSession) -> None:
    public_id = uuid4()
    await add_athlete(db_session, athlete_public_id=public_id)

    with pytest.raises(IntegrityError):
        await add_athlete(db_session, athlete_public_id=public_id)


async def test_athlete_user_id_is_unique_when_present(
    db_session: AsyncSession,
) -> None:
    user = await add_user(db_session, telegram_id=1002)
    await add_athlete(db_session, user_id=user.id)

    with pytest.raises(IntegrityError):
        await add_athlete(db_session, user_id=user.id)


async def test_multiple_athletes_without_users_are_allowed(
    db_session: AsyncSession,
) -> None:
    first = await add_athlete(db_session)
    second = await add_athlete(db_session)

    assert first.user_id is None
    assert second.user_id is None
    assert first.athlete_public_id.version == 4
    assert second.athlete_public_id.version == 4
    assert first.athlete_public_id != second.athlete_public_id


async def test_registration_invite_cannot_target_athlete(
    db_session: AsyncSession,
) -> None:
    athlete = await add_athlete(db_session)
    db_session.add(
        BotInviteModel(
            token_hash=f"registration-{uuid4()}",
            purpose=BotInvitePurpose.REGISTRATION,
            athlete_id=athlete.id,
            is_active=True,
            expires_at=None,
            revoked_at=None,
            consumed_at=None,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_athlete_link_invite_requires_athlete_target(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        BotInviteModel(
            token_hash=f"athlete-link-{uuid4()}",
            purpose=BotInvitePurpose.ATHLETE_LINK,
            athlete_id=None,
            is_active=True,
            expires_at=None,
            revoked_at=None,
            consumed_at=None,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_role_pair_is_unique(db_session: AsyncSession) -> None:
    user = await add_user(db_session, telegram_id=1003)
    role = RoleModel(
        code=f"test-role-{uuid4()}",
        name="Trainer",
        is_system=True,
        is_active=True,
    )
    db_session.add(role)
    await db_session.flush()

    db_session.add(
        UserRoleModel(
            user_id=user.id,
            role_id=role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    await db_session.flush()

    db_session.add(
        UserRoleModel(
            user_id=user.id,
            role_id=role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_training_session_rule_and_start_are_unique(
    db_session: AsyncSession,
) -> None:
    trainer = await add_user(db_session, telegram_id=1004)
    group = await add_training_group(db_session, trainer.id)
    rule = await add_schedule_rule(db_session, group.id)
    await add_training_session(
        db_session,
        group_id=group.id,
        trainer_id=trainer.id,
        schedule_rule_id=rule.id,
    )

    with pytest.raises(IntegrityError):
        await add_training_session(
            db_session,
            group_id=group.id,
            trainer_id=trainer.id,
            schedule_rule_id=rule.id,
        )


async def test_training_group_can_exist_without_trainer(
    db_session: AsyncSession,
) -> None:
    group = await add_training_group(db_session, trainer_id=None)

    assert group.trainer_id is None
    assert group.group_type is TrainingGroupType.REGULAR


async def test_two_active_subscriptions_for_one_athlete_are_rejected(
    db_session: AsyncSession,
) -> None:
    actor, athlete, group, plan = await add_subscription_context(db_session)
    await add_subscription(
        db_session,
        athlete_id=athlete.id,
        group_id=group.id,
        plan_id=plan.id,
        activated_by_user_id=actor.id,
        status=SubscriptionStatus.ACTIVE,
    )

    with pytest.raises(IntegrityError):
        await add_subscription(
            db_session,
            athlete_id=athlete.id,
            group_id=group.id,
            plan_id=plan.id,
            activated_by_user_id=actor.id,
            status=SubscriptionStatus.ACTIVE,
        )


async def test_active_and_historical_subscriptions_can_coexist(
    db_session: AsyncSession,
) -> None:
    actor, athlete, group, plan = await add_subscription_context(db_session)

    for status in (
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.EXPIRED,
        SubscriptionStatus.EXPIRED,
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.CANCELLED,
    ):
        await add_subscription(
            db_session,
            athlete_id=athlete.id,
            group_id=group.id,
            plan_id=plan.id,
            activated_by_user_id=actor.id,
            status=status,
        )


async def test_attendance_session_and_athlete_are_unique(
    db_session: AsyncSession,
) -> None:
    actor, athlete, group, plan = await add_subscription_context(db_session)
    subscription = await add_subscription(
        db_session,
        athlete_id=athlete.id,
        group_id=group.id,
        plan_id=plan.id,
        activated_by_user_id=actor.id,
        status=SubscriptionStatus.ACTIVE,
    )
    rule = await add_schedule_rule(db_session, group.id)
    training_session = await add_training_session(
        db_session,
        group_id=group.id,
        trainer_id=actor.id,
        schedule_rule_id=rule.id,
    )

    db_session.add(
        AttendanceModel(
            training_session_id=training_session.id,
            athlete_id=athlete.id,
            subscription_id=subscription.id,
            confirmed_by_user_id=actor.id,
            source=AttendanceSource.QR,
            status=AttendanceStatus.CONFIRMED,
            confirmed_at=NOW,
        )
    )
    await db_session.flush()

    db_session.add(
        AttendanceModel(
            training_session_id=training_session.id,
            athlete_id=athlete.id,
            subscription_id=subscription.id,
            confirmed_by_user_id=actor.id,
            source=AttendanceSource.MANUAL,
            status=AttendanceStatus.CONFIRMED,
            confirmed_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_notification_idempotency_key_is_unique(
    db_session: AsyncSession,
) -> None:
    recipient = await add_user(db_session, telegram_id=1005)
    idempotency_key = "TRAINER_SESSION_MINUS_5:42"

    db_session.add(
        NotificationModel(
            recipient_user_id=recipient.id,
            training_session_id=None,
            type="TRAINER_SESSION_MINUS_5",
            scheduled_at=NOW,
            sent_at=None,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
            attempts=0,
        )
    )
    await db_session.flush()

    db_session.add(
        NotificationModel(
            recipient_user_id=recipient.id,
            training_session_id=None,
            type="TRAINER_SESSION_MINUS_5",
            scheduled_at=NOW,
            sent_at=None,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
            attempts=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
