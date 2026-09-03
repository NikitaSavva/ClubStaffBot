from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from domain.club import TrainingGroupType
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.models import (
    AthleteModel,
    GroupNameModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    UserModel,
)
from infrastructure.database.readers import (
    SqlAlchemyLatestAthleteSubscriptionReader,
)

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


async def add_context(
    session: AsyncSession,
) -> tuple[UserModel, AthleteModel, SubscriptionPlanModel, TrainingGroupModel]:
    suffix = uuid4().hex[:10]
    actor = UserModel(
        telegram_id=90_000_000 + uuid4().int % 1_000_000_000,
        username=f"latest_{suffix}",
        first_name="Admin",
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    athlete = AthleteModel(
        user_id=None,
        first_name="Иван",
        last_name=f"Иванов {suffix}",
        birth_date=date(1991, 12, 27),
        phone=None,
        is_active=True,
    )
    direction = SportDirectionModel(
        code=f"LATEST_{suffix}",
        name="Кикбоксинг",
        is_active=True,
    )
    group_name = GroupNameModel(name=f"Взрослые {suffix}")
    plan = SubscriptionPlanModel(
        code=f"LATEST_PLAN_{suffix}",
        name="12 посещений",
        visit_limit=12,
        duration_months=1,
        price=Decimal("5000"),
        is_unlimited=False,
        access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        required_group_type=None,
        is_active=True,
    )
    session.add_all([actor, athlete, direction, group_name, plan])
    await session.flush()
    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=None,
        name_id=group_name.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add(group)
    await session.flush()
    return actor, athlete, plan, group


def make_subscription(
    *,
    actor: UserModel,
    athlete: AthleteModel,
    plan: SubscriptionPlanModel,
    group: TrainingGroupModel,
    status: SubscriptionStatus,
    created_at: datetime,
    expires_at: datetime = NOW + timedelta(days=20),
    remaining_visits: int = 7,
) -> SubscriptionModel:
    return SubscriptionModel(
        athlete_id=athlete.id,
        group_id=group.id,
        plan_id=plan.id,
        activated_by_user_id=actor.id,
        activated_at=created_at,
        starts_at=created_at,
        expires_at=expires_at,
        activation_price=plan.price,
        remaining_visits=remaining_visits,
        status=status,
        created_at=created_at,
    )


@pytest.mark.parametrize(
    "newer_status",
    [SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED],
)
async def test_newer_inactive_subscription_wins_over_older_active(
    db_session: AsyncSession,
    newer_status: SubscriptionStatus,
) -> None:
    actor, athlete, plan, group = await add_context(db_session)
    older = make_subscription(
        actor=actor,
        athlete=athlete,
        plan=plan,
        group=group,
        status=SubscriptionStatus.ACTIVE,
        created_at=NOW - timedelta(days=20),
    )
    newer = make_subscription(
        actor=actor,
        athlete=athlete,
        plan=plan,
        group=group,
        status=newer_status,
        created_at=NOW - timedelta(days=10),
    )
    db_session.add_all([older, newer])
    await db_session.flush()

    result = await SqlAlchemyLatestAthleteSubscriptionReader(
        db_session
    ).get_by_athlete_id(athlete.id)

    assert result is not None
    assert result.latest is not None
    assert result.latest.subscription_id == newer.id
    assert result.latest.status is newer_status


async def test_elapsed_active_and_zero_remaining_are_not_filtered(
    db_session: AsyncSession,
) -> None:
    actor, athlete, plan, group = await add_context(db_session)
    elapsed = make_subscription(
        actor=actor,
        athlete=athlete,
        plan=plan,
        group=group,
        status=SubscriptionStatus.ACTIVE,
        created_at=NOW,
        expires_at=NOW - timedelta(seconds=1),
        remaining_visits=0,
    )
    db_session.add(elapsed)
    await db_session.flush()

    result = await SqlAlchemyLatestAthleteSubscriptionReader(
        db_session
    ).get_by_athlete_id(athlete.id)

    assert result is not None
    assert result.latest is not None
    assert result.latest.subscription_id == elapsed.id
    assert result.latest.status is SubscriptionStatus.ACTIVE
    assert result.latest.remaining_visits == 0


async def test_equal_created_at_is_ordered_by_descending_id(
    db_session: AsyncSession,
) -> None:
    actor, athlete, plan, group = await add_context(db_session)
    first = make_subscription(
        actor=actor,
        athlete=athlete,
        plan=plan,
        group=group,
        status=SubscriptionStatus.EXPIRED,
        created_at=NOW,
    )
    second = make_subscription(
        actor=actor,
        athlete=athlete,
        plan=plan,
        group=group,
        status=SubscriptionStatus.CANCELLED,
        created_at=NOW,
    )
    db_session.add_all([first, second])
    await db_session.flush()

    result = await SqlAlchemyLatestAthleteSubscriptionReader(
        db_session
    ).get_by_athlete_id(athlete.id)

    assert result is not None
    assert result.latest is not None
    assert result.latest.subscription_id == second.id


async def test_athlete_without_subscription_returns_controlled_empty_result(
    db_session: AsyncSession,
) -> None:
    _, athlete, _, _ = await add_context(db_session)

    result = await SqlAlchemyLatestAthleteSubscriptionReader(
        db_session
    ).get_by_athlete_id(athlete.id)

    assert result is not None
    assert result.athlete_full_name.startswith("Иван Иванов")
    assert result.latest is None


async def test_missing_athlete_returns_none(db_session: AsyncSession) -> None:
    result = await SqlAlchemyLatestAthleteSubscriptionReader(
        db_session
    ).get_by_athlete_id(2_147_483_647)

    assert result is None
