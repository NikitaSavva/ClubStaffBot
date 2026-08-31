from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.subscriptions import (
    GetMySubscriptionInteractor,
    GetMySubscriptionQuery,
)
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from domain.subscriptions import (
    SubscriptionAccessScope,
    SubscriptionStatus,
)
from infrastructure.database.models import (
    AthleteModel,
    GroupNameModel,
    RoleModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.readers import SqlAlchemyMySubscriptionReader
from infrastructure.database.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)


class FrozenClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


@dataclass(frozen=True, slots=True)
class ContextIds:
    user_id: int
    telegram_id: int
    athlete_id: int
    group_id: int
    group_name_id: int
    direction_id: int
    plan_id: int


async def ensure_athlete_role(session: AsyncSession) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(
            RoleModel.code == SystemRoleCode.ATHLETE.value
        )
    )
    if role is None:
        role = RoleModel(
            code=SystemRoleCode.ATHLETE.value,
            name="Athlete",
            is_system=True,
            is_active=True,
        )
        session.add(role)
        await session.flush()
    return role


async def add_context(
    session: AsyncSession,
    *,
    plan_active: bool = True,
    subscription_status: SubscriptionStatus | None = (
        SubscriptionStatus.ACTIVE
    ),
    starts_at: datetime = NOW - timedelta(days=5),
    expires_at: datetime = NOW + timedelta(days=25),
    remaining_visits: int | None = 7,
) -> ContextIds:
    suffix = uuid4().hex[:10]
    role = await ensure_athlete_role(session)
    user = UserModel(
        telegram_id=80_000_000 + uuid4().int % 1_000_000_000,
        username=f"athlete_{suffix}",
        first_name="Иван",
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    direction = SportDirectionModel(
        code=f"MY_SUB_{suffix}",
        name="Кикбоксинг",
        short_name="K1",
        is_active=True,
    )
    group_name = GroupNameModel(name=f"Взрослые {suffix}")
    plan = SubscriptionPlanModel(
        code=f"MY_SUB_PLAN_{suffix}",
        name="12 посещений",
        visit_limit=12,
        duration_months=1,
        price=Decimal("6000"),
        is_unlimited=False,
        access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        required_group_type=None,
        is_active=plan_active,
    )
    session.add_all([user, direction, group_name, plan])
    await session.flush()
    athlete = AthleteModel(
        user_id=user.id,
        first_name="Иван",
        last_name="Иванов",
        birth_date=None,
        phone=None,
        is_active=True,
    )
    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=None,
        name_id=group_name.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add_all(
        [
            athlete,
            group,
            UserRoleModel(
                user_id=user.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            ),
        ]
    )
    await session.flush()
    if subscription_status is not None:
        session.add(
            SubscriptionModel(
                athlete_id=athlete.id,
                group_id=group.id,
                plan_id=plan.id,
                activated_by_user_id=user.id,
                activated_at=starts_at,
                starts_at=starts_at,
                expires_at=expires_at,
                activation_price=plan.price,
                remaining_visits=remaining_visits,
                status=subscription_status,
            )
        )
        await session.flush()
    return ContextIds(
        user_id=user.id,
        telegram_id=user.telegram_id,
        athlete_id=athlete.id,
        group_id=group.id,
        group_name_id=group_name.id,
        direction_id=direction.id,
        plan_id=plan.id,
    )


async def cleanup_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: ContextIds,
) -> None:
    async with session_factory() as session:
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.plan_id == context.plan_id
            )
        )
        await session.execute(
            delete(UserRoleModel).where(
                UserRoleModel.user_id == context.user_id
            )
        )
        await session.execute(
            delete(AthleteModel).where(AthleteModel.id == context.athlete_id)
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id == context.group_id
            )
        )
        await session.execute(
            delete(SubscriptionPlanModel).where(
                SubscriptionPlanModel.id == context.plan_id
            )
        )
        await session.execute(
            delete(GroupNameModel).where(
                GroupNameModel.id == context.group_name_id
            )
        )
        await session.execute(
            delete(SportDirectionModel).where(
                SportDirectionModel.id == context.direction_id
            )
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == context.user_id)
        )
        await session.commit()


async def test_reader_loads_inactive_plan_and_simple_group_in_one_query(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context: ContextIds | None = None
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(" ".join(statement.lower().split()))

    try:
        async with session_factory() as setup:
            context = await add_context(setup, plan_active=False)
            await setup.commit()

        event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
        async with session_factory() as session:
            result = await SqlAlchemyMySubscriptionReader(
                session
            ).get_by_user_id(context.user_id)
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )

        assert len(statements) == 1
        assert "schedule_rules" not in statements[0]
        assert result is not None
        assert result.persisted_active is not None
        assert result.persisted_active.plan_name == "12 посещений"
        assert result.persisted_active.subscription.remaining_visits == 7
        assert result.persisted_active.group is not None
        assert result.persisted_active.group.direction_name == "Кикбоксинг"
        assert result.persisted_active.group.group_name.startswith("Взрослые")
    finally:
        if context is not None:
            await cleanup_context(session_factory, context)
        await engine.dispose()


async def test_reader_does_not_return_expired_or_cancelled_history(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context: ContextIds | None = None
    try:
        async with session_factory() as setup:
            context = await add_context(
                setup,
                subscription_status=SubscriptionStatus.EXPIRED,
            )
            setup.add(
                SubscriptionModel(
                    athlete_id=context.athlete_id,
                    group_id=context.group_id,
                    plan_id=context.plan_id,
                    activated_by_user_id=context.user_id,
                    activated_at=NOW - timedelta(days=60),
                    starts_at=NOW - timedelta(days=60),
                    expires_at=NOW - timedelta(days=30),
                    activation_price=Decimal("6000"),
                    remaining_visits=3,
                    status=SubscriptionStatus.CANCELLED,
                )
            )
            await setup.commit()

        async with session_factory() as session:
            result = await SqlAlchemyMySubscriptionReader(
                session
            ).get_by_user_id(context.user_id)

        assert result is not None
        assert result.persisted_active is None
    finally:
        if context is not None:
            await cleanup_context(session_factory, context)
        await engine.dispose()


async def test_elapsed_active_read_does_not_write_or_change_status(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context: ContextIds | None = None
    writes: list[str] = []

    def record_writes(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        normalized = statement.lstrip().lower()
        if normalized.startswith(("update", "insert", "delete")):
            writes.append(normalized)

    try:
        async with session_factory() as setup:
            context = await add_context(setup, expires_at=NOW)
            await setup.commit()

        event.listen(engine.sync_engine, "before_cursor_execute", record_writes)
        clock = FrozenClock()
        async with session_factory() as session:
            result = await GetMySubscriptionInteractor(
                user_repository=SqlAlchemyUserRepository(session),
                role_repository=SqlAlchemyRoleRepository(session),
                reader=SqlAlchemyMySubscriptionReader(session),
                clock=clock,
            )(
                GetMySubscriptionQuery(
                    actor_telegram_id=context.telegram_id,
                )
            )
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            record_writes,
        )

        assert result.current is None
        assert clock.calls == 1
        assert not writes
        async with session_factory() as verification:
            status = await verification.scalar(
                select(SubscriptionModel.status).where(
                    SubscriptionModel.athlete_id == context.athlete_id
                )
            )
            assert status is SubscriptionStatus.ACTIVE
    finally:
        if context is not None:
            await cleanup_context(session_factory, context)
        await engine.dispose()
