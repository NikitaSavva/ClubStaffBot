import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.subscriptions import (
    ActivateSubscriptionCommand,
    ActivateSubscriptionInteractor,
    ActivateSubscriptionResult,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    SubscriptionPlanInactiveError,
)
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    GroupNameModel,
    RoleModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySubscriptionPlanRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyTrainingGroupRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


async def ensure_role(
    session: AsyncSession,
    code: SystemRoleCode,
) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(RoleModel.code == code.value)
    )
    if role is None:
        role = RoleModel(
            code=code.value,
            name=code.value.title(),
            is_system=True,
            is_active=True,
        )
        session.add(role)
        await session.flush()
    return role


async def add_context(
    session: AsyncSession,
    *,
    plan_scope: SubscriptionAccessScope = (
        SubscriptionAccessScope.SPECIFIC_GROUP
    ),
    plan_active: bool = True,
    stale_active: bool = False,
) -> tuple[UserModel, AthleteModel, TrainingGroupModel, SubscriptionPlanModel]:
    suffix = uuid4().hex[:10]
    role = await ensure_role(session, SystemRoleCode.ADMINISTRATOR)
    actor = UserModel(
        telegram_id=70_000_000 + uuid4().int % 1_000_000_000,
        username=f"admin_{suffix}",
        first_name="Admin",
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    athlete = AthleteModel(
        user_id=None,
        first_name="Иван",
        last_name=suffix,
        birth_date=date(1991, 12, 27),
        phone=None,
        is_active=True,
    )
    direction = SportDirectionModel(
        code=f"SUB_{suffix}",
        name=f"Кикбоксинг {suffix}",
        is_active=True,
    )
    group_name = GroupNameModel(name=f"Взрослые {suffix}")
    plan = SubscriptionPlanModel(
        code=f"SUB_PLAN_{suffix}",
        name="8 посещений",
        visit_limit=(
            8
            if plan_scope is SubscriptionAccessScope.SPECIFIC_GROUP
            else None
        ),
        duration_months=1,
        price=Decimal("4000"),
        is_unlimited=(
            plan_scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS
        ),
        access_scope=plan_scope,
        required_group_type=None,
        is_active=plan_active,
    )
    session.add_all([actor, athlete, direction, group_name, plan])
    await session.flush()
    session.add(
        UserRoleModel(
            user_id=actor.id,
            role_id=role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=None,
        name_id=group_name.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add(group)
    await session.flush()
    if stale_active:
        session.add(
            SubscriptionModel(
                athlete_id=athlete.id,
                group_id=group.id,
                plan_id=plan.id,
                activated_by_user_id=actor.id,
                activated_at=NOW - timedelta(days=31),
                starts_at=NOW - timedelta(days=31),
                expires_at=NOW,
                activation_price=plan.price,
                remaining_visits=1,
                status=SubscriptionStatus.ACTIVE,
            )
        )
    await session.flush()
    return actor, athlete, group, plan


async def execute_activation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_telegram_id: int,
    athlete_id: int,
    plan_id: int,
    group_id: int | None,
) -> ActivateSubscriptionResult:
    async with session_factory() as session:
        return await ActivateSubscriptionInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            training_group_repository=SqlAlchemyTrainingGroupRepository(
                session
            ),
            subscription_plan_repository=(
                SqlAlchemySubscriptionPlanRepository(session)
            ),
            subscription_repository=SqlAlchemySubscriptionRepository(session),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
        )(
            ActivateSubscriptionCommand(
                actor_telegram_id=actor_telegram_id,
                athlete_id=athlete_id,
                subscription_plan_id=plan_id,
                training_group_id=group_id,
            )
        )


async def setup_committed_context(
    session_factory: async_sessionmaker[AsyncSession],
    **kwargs: object,
) -> tuple[int, int, int, int]:
    async with session_factory() as session:
        actor, athlete, group, plan = await add_context(session, **kwargs)
        await session.commit()
        return actor.telegram_id, athlete.id, group.id, plan.id


async def cleanup_contexts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        plan_ids = tuple(
            await session.scalars(
                select(SubscriptionPlanModel.id).where(
                    SubscriptionPlanModel.code.like("SUB_PLAN_%")
                )
            )
        )
        if not plan_ids:
            return
        subscriptions = (
            await session.execute(
                select(
                    SubscriptionModel.id,
                    SubscriptionModel.athlete_id,
                    SubscriptionModel.group_id,
                    SubscriptionModel.activated_by_user_id,
                ).where(SubscriptionModel.plan_id.in_(plan_ids))
            )
        ).all()
        subscription_ids = tuple(row.id for row in subscriptions)
        athlete_ids = tuple({row.athlete_id for row in subscriptions})
        group_ids = tuple(
            {row.group_id for row in subscriptions if row.group_id is not None}
        )
        actor_ids = tuple({row.activated_by_user_id for row in subscriptions})
        group_context = (
            await session.execute(
                select(
                    TrainingGroupModel.name_id,
                    TrainingGroupModel.direction_id,
                ).where(TrainingGroupModel.id.in_(group_ids))
            )
        ).all()
        group_name_ids = tuple({row.name_id for row in group_context})
        direction_ids = tuple({row.direction_id for row in group_context})

        if subscription_ids:
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.entity_type == "SUBSCRIPTION",
                    AuditLogModel.entity_id.in_(subscription_ids),
                )
            )
        if actor_ids:
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.actor_user_id.in_(actor_ids)
                )
            )
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.plan_id.in_(plan_ids)
            )
        )
        if actor_ids:
            await session.execute(
                delete(UserRoleModel).where(UserRoleModel.user_id.in_(actor_ids))
            )
        if athlete_ids:
            await session.execute(
                delete(AthleteModel).where(AthleteModel.id.in_(athlete_ids))
            )
        if group_ids:
            await session.execute(
                delete(TrainingGroupModel).where(
                    TrainingGroupModel.id.in_(group_ids)
                )
            )
        await session.execute(
            delete(SubscriptionPlanModel).where(
                SubscriptionPlanModel.id.in_(plan_ids)
            )
        )
        if group_name_ids:
            await session.execute(
                delete(GroupNameModel).where(
                    GroupNameModel.id.in_(group_name_ids)
                )
            )
        if direction_ids:
            await session.execute(
                delete(SportDirectionModel).where(
                    SportDirectionModel.id.in_(direction_ids)
                )
            )
        if actor_ids:
            await session.execute(
                delete(UserModel).where(UserModel.id.in_(actor_ids))
            )
        await session.commit()


async def test_stale_active_update_reaches_postgres_before_active_insert(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update subscriptions") or normalized.startswith(
            "insert into subscriptions"
        ):
            statements.append(normalized)

    event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        actor_telegram_id, athlete_id, group_id, plan_id = (
            await setup_committed_context(
                session_factory,
                stale_active=True,
            )
        )
        statements.clear()

        result = await execute_activation(
            session_factory,
            actor_telegram_id=actor_telegram_id,
            athlete_id=athlete_id,
            plan_id=plan_id,
            group_id=group_id,
        )

        assert result.remaining_visits == 8
        assert len(statements) == 2
        assert statements[0].startswith("update subscriptions")
        assert statements[1].startswith("insert into subscriptions")

        async with session_factory() as verification:
            rows = (
                await verification.scalars(
                    select(SubscriptionModel)
                    .where(SubscriptionModel.athlete_id == athlete_id)
                    .order_by(SubscriptionModel.id)
                )
            ).all()
            assert [row.status for row in rows] == [
                SubscriptionStatus.EXPIRED,
                SubscriptionStatus.ACTIVE,
            ]
            assert rows[1].remaining_visits == 8
            audit_count = await verification.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                    AuditLogModel.entity_id == result.subscription_id,
                )
            )
            assert audit_count == 1
    finally:
        await cleanup_contexts(session_factory)
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )
        await engine.dispose()


async def test_lazy_expiration_rolls_back_when_later_validation_fails(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        actor_telegram_id, athlete_id, group_id, plan_id = (
            await setup_committed_context(
                session_factory,
                stale_active=True,
                plan_active=False,
            )
        )

        with pytest.raises(SubscriptionPlanInactiveError):
            await execute_activation(
                session_factory,
                actor_telegram_id=actor_telegram_id,
                athlete_id=athlete_id,
                plan_id=plan_id,
                group_id=group_id,
            )

        async with session_factory() as verification:
            subscriptions = (
                await verification.scalars(
                    select(SubscriptionModel).where(
                        SubscriptionModel.athlete_id == athlete_id
                    )
                )
            ).all()
            assert len(subscriptions) == 1
            assert subscriptions[0].status is SubscriptionStatus.ACTIVE
            audit_count = await verification.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                    AuditLogModel.entity_id == subscriptions[0].id,
                )
            )
            assert audit_count == 0
    finally:
        await cleanup_contexts(session_factory)
        await engine.dispose()


@pytest.mark.parametrize("stale_active", [False, True])
async def test_concurrent_activations_create_at_most_one_new_active(
    database_url: str,
    stale_active: bool,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        actor_telegram_id, athlete_id, group_id, plan_id = (
            await setup_committed_context(
                session_factory,
                stale_active=stale_active,
            )
        )

        async def attempt() -> ActivateSubscriptionResult | BaseException:
            try:
                return await execute_activation(
                    session_factory,
                    actor_telegram_id=actor_telegram_id,
                    athlete_id=athlete_id,
                    plan_id=plan_id,
                    group_id=group_id,
                )
            except BaseException as error:
                return error

        outcomes = await asyncio.gather(attempt(), attempt())

        assert sum(isinstance(item, ActivateSubscriptionResult) for item in outcomes) == 1
        assert sum(
            isinstance(item, ActiveSubscriptionAlreadyExistsError)
            for item in outcomes
        ) == 1
        async with session_factory() as verification:
            active_count = await verification.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.athlete_id == athlete_id,
                    SubscriptionModel.status == SubscriptionStatus.ACTIVE,
                )
            )
            audit_count = await verification.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                    AuditLogModel.payload["athlete_id"].as_integer()
                    == athlete_id,
                )
            )
            assert active_count == 1
            assert audit_count == 1
    finally:
        await cleanup_contexts(session_factory)
        await engine.dispose()


@pytest.mark.parametrize("materialize", ["flush", "commit"])
async def test_partial_unique_violation_is_controlled_at_uow_boundary(
    database_url: str,
    materialize: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        actor_telegram_id, athlete_id, group_id, plan_id = (
            await setup_committed_context(session_factory)
        )
        await execute_activation(
            session_factory,
            actor_telegram_id=actor_telegram_id,
            athlete_id=athlete_id,
            plan_id=plan_id,
            group_id=group_id,
        )

        async with session_factory() as session:
            uow = SqlAlchemyUnitOfWork(session)
            with pytest.raises(ActiveSubscriptionAlreadyExistsError):
                async with uow:
                    session.add(
                        SubscriptionModel(
                            athlete_id=athlete_id,
                            group_id=group_id,
                            plan_id=plan_id,
                            activated_by_user_id=(
                                await session.scalar(
                                    select(UserModel.id).where(
                                        UserModel.telegram_id
                                        == actor_telegram_id
                                    )
                                )
                            ),
                            activated_at=NOW,
                            starts_at=NOW,
                            expires_at=NOW + timedelta(days=1),
                            activation_price=Decimal("4000"),
                            remaining_visits=8,
                            status=SubscriptionStatus.ACTIVE,
                        )
                    )
                    materializer: Callable[[], object] = (
                        uow.flush if materialize == "flush" else uow.commit
                    )
                    await materializer()
    finally:
        await cleanup_contexts(session_factory)
        await engine.dispose()
