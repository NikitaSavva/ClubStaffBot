from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.subscriptions import (
    CorrectSubscriptionCommand,
    CorrectSubscriptionInteractor,
    CorrectSubscriptionOutcome,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    LatestSubscriptionChangedError,
)
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    RoleModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySubscriptionPlanRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


async def add_context(
    session: AsyncSession,
    *,
    target_status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    with_other_active: bool = False,
    with_newer: bool = False,
) -> tuple[UserModel, AthleteModel, SubscriptionModel]:
    suffix = uuid4().hex[:10]
    role = await session.scalar(
        select(RoleModel).where(
            RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
        )
    )
    if role is None:
        role = RoleModel(
            code=SystemRoleCode.ADMINISTRATOR.value,
            name="Administrator",
            is_system=True,
            is_active=True,
        )
        session.add(role)
        await session.flush()
    actor = UserModel(
        telegram_id=95_000_000 + uuid4().int % 1_000_000_000,
        username=f"correction_{suffix}",
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
    plan = SubscriptionPlanModel(
        code=f"CORRECTION_{suffix}",
        name="12 посещений",
        visit_limit=12,
        duration_months=1,
        price=Decimal("5000"),
        is_unlimited=False,
        access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
        required_group_type=None,
        is_active=True,
    )
    session.add_all([actor, athlete, plan])
    await session.flush()
    session.add(
        UserRoleModel(
            user_id=actor.id,
            role_id=role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    target = SubscriptionModel(
        athlete_id=athlete.id,
        group_id=None,
        plan_id=plan.id,
        activated_by_user_id=actor.id,
        activated_at=NOW - timedelta(days=10),
        starts_at=NOW - timedelta(days=10),
        expires_at=NOW + timedelta(days=20),
        activation_price=plan.price,
        remaining_visits=12,
        status=target_status,
        created_at=NOW - timedelta(days=2),
    )
    session.add(target)
    await session.flush()
    if with_other_active:
        session.add(
            SubscriptionModel(
                athlete_id=athlete.id,
                group_id=None,
                plan_id=plan.id,
                activated_by_user_id=actor.id,
                activated_at=NOW - timedelta(days=20),
                starts_at=NOW - timedelta(days=20),
                expires_at=NOW + timedelta(days=10),
                activation_price=plan.price,
                remaining_visits=8,
                status=SubscriptionStatus.ACTIVE,
                created_at=NOW - timedelta(days=3),
            )
        )
    if with_newer:
        session.add(
            SubscriptionModel(
                athlete_id=athlete.id,
                group_id=None,
                plan_id=plan.id,
                activated_by_user_id=actor.id,
                activated_at=NOW - timedelta(days=1),
                starts_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=29),
                activation_price=plan.price,
                remaining_visits=6,
                status=SubscriptionStatus.CANCELLED,
                created_at=NOW - timedelta(days=1),
            )
        )
    await session.commit()
    return actor, athlete, target


def interactor(
    session: AsyncSession,
    *,
    audit_repository: object | None = None,
) -> CorrectSubscriptionInteractor:
    return CorrectSubscriptionInteractor(
        user_repository=SqlAlchemyUserRepository(session),
        athlete_repository=SqlAlchemyAthleteRepository(session),
        role_repository=SqlAlchemyRoleRepository(session),
        subscription_plan_repository=SqlAlchemySubscriptionPlanRepository(
            session
        ),
        subscription_repository=SqlAlchemySubscriptionRepository(session),
        audit_log_repository=(
            audit_repository  # type: ignore[arg-type]
            if audit_repository is not None
            else SqlAlchemyAuditLogRepository(session)
        ),
        unit_of_work=SqlAlchemyUnitOfWork(session),
    )


def command(
    actor: UserModel,
    athlete: AthleteModel,
    target: SubscriptionModel,
    *,
    remaining_visits: int | None = 7,
    expires_at: datetime | None = None,
    status: SubscriptionStatus | None = SubscriptionStatus.EXPIRED,
) -> CorrectSubscriptionCommand:
    return CorrectSubscriptionCommand(
        actor_telegram_id=actor.telegram_id,
        athlete_id=athlete.id,
        subscription_id=target.id,
        remaining_visits_is_set=remaining_visits is not None,
        remaining_visits=remaining_visits,
        expires_at=expires_at or NOW + timedelta(days=5),
        status=status,
    )


async def cleanup_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_id: int,
    athlete_id: int,
    plan_id: int,
) -> None:
    async with session_factory() as session:
        subscription_ids = tuple(
            await session.scalars(
                select(SubscriptionModel.id).where(
                    SubscriptionModel.athlete_id == athlete_id
                )
            )
        )
        if subscription_ids:
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.entity_type == "SUBSCRIPTION",
                    AuditLogModel.entity_id.in_(subscription_ids),
                )
            )
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.athlete_id == athlete_id
            )
        )
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id == actor_id)
        )
        await session.execute(
            delete(AthleteModel).where(AthleteModel.id == athlete_id)
        )
        await session.execute(
            delete(SubscriptionPlanModel).where(
                SubscriptionPlanModel.id == plan_id
            )
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == actor_id)
        )
        await session.commit()


async def test_update_and_audit_commit_atomically(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    cleanup_ids: tuple[int, int, int] | None = None
    try:
        async with session_factory() as session:
            actor, athlete, target = await add_context(session)
            target_id = target.id
            cleanup_ids = (actor.id, athlete.id, target.plan_id)
            result = await interactor(session)(command(actor, athlete, target))

        assert result.outcome is CorrectSubscriptionOutcome.CORRECTED
        async with session_factory() as verification:
            updated = await verification.get(SubscriptionModel, target_id)
            audit = await verification.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.entity_id == target_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
            assert updated is not None
            assert updated.remaining_visits == 7
            assert updated.expires_at == NOW + timedelta(days=5)
            assert updated.status is SubscriptionStatus.EXPIRED
            assert audit is not None
            assert audit.actor_user_id == actor.id
            assert audit.payload is not None
            assert audit.payload["changes"] == {
                "remaining_visits": {"before": 12, "after": 7},
                "expires_at": {
                    "before": (NOW + timedelta(days=20)).isoformat(),
                    "after": (NOW + timedelta(days=5)).isoformat(),
                },
                "status": {"before": "ACTIVE", "after": "EXPIRED"},
            }
            expired_audit = await verification.scalar(
                select(AuditLogModel.id).where(
                    AuditLogModel.entity_id == target_id,
                    AuditLogModel.action == "SUBSCRIPTION_EXPIRED",
                )
            )
            assert expired_audit is None
    finally:
        if cleanup_ids is not None:
            await cleanup_context(
                session_factory,
                actor_id=cleanup_ids[0],
                athlete_id=cleanup_ids[1],
                plan_id=cleanup_ids[2],
            )
        await engine.dispose()


class FailingAuditRepository:
    async def add(self, **record: object) -> None:
        raise RuntimeError("audit insert failed")


async def test_audit_failure_rolls_back_subscription(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    cleanup_ids: tuple[int, int, int] | None = None
    try:
        async with session_factory() as session:
            actor, athlete, target = await add_context(session)
            target_id = target.id
            cleanup_ids = (actor.id, athlete.id, target.plan_id)
            with pytest.raises(RuntimeError, match="audit insert failed"):
                await interactor(
                    session,
                    audit_repository=FailingAuditRepository(),
                )(command(actor, athlete, target))

        async with session_factory() as verification:
            unchanged = await verification.get(SubscriptionModel, target_id)
            assert unchanged is not None
            assert unchanged.remaining_visits == 12
            assert unchanged.expires_at == NOW + timedelta(days=20)
            assert unchanged.status is SubscriptionStatus.ACTIVE
            audit_count = await verification.scalar(
                select(AuditLogModel.id).where(
                    AuditLogModel.entity_id == target_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
            assert audit_count is None
    finally:
        if cleanup_ids is not None:
            await cleanup_context(
                session_factory,
                actor_id=cleanup_ids[0],
                athlete_id=cleanup_ids[1],
                plan_id=cleanup_ids[2],
            )
        await engine.dispose()


async def test_other_active_conflict_excludes_target_itself(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    cleanup_ids: tuple[int, int, int] | None = None
    try:
        async with session_factory() as session:
            actor, athlete, target = await add_context(
                session,
                target_status=SubscriptionStatus.EXPIRED,
                with_other_active=True,
            )
            cleanup_ids = (actor.id, athlete.id, target.plan_id)
            with pytest.raises(ActiveSubscriptionAlreadyExistsError):
                await interactor(session)(
                    command(
                        actor,
                        athlete,
                        target,
                        remaining_visits=12,
                        expires_at=target.expires_at,
                        status=SubscriptionStatus.ACTIVE,
                    )
                )
    finally:
        if cleanup_ids is not None:
            await cleanup_context(
                session_factory,
                actor_id=cleanup_ids[0],
                athlete_id=cleanup_ids[1],
                plan_id=cleanup_ids[2],
            )
        await engine.dispose()


async def test_newer_subscription_causes_rollback_without_audit(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    cleanup_ids: tuple[int, int, int] | None = None
    try:
        async with session_factory() as session:
            actor, athlete, target = await add_context(
                session,
                target_status=SubscriptionStatus.EXPIRED,
                with_newer=True,
            )
            target_id = target.id
            cleanup_ids = (actor.id, athlete.id, target.plan_id)
            with pytest.raises(LatestSubscriptionChangedError):
                await interactor(session)(command(actor, athlete, target))

        async with session_factory() as verification:
            unchanged = await verification.get(SubscriptionModel, target_id)
            assert unchanged is not None
            assert unchanged.remaining_visits == 12
            audit = await verification.scalar(
                select(AuditLogModel.id).where(
                    AuditLogModel.entity_id == target_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
            assert audit is None
    finally:
        if cleanup_ids is not None:
            await cleanup_context(
                session_factory,
                actor_id=cleanup_ids[0],
                athlete_id=cleanup_ids[1],
                plan_id=cleanup_ids[2],
            )
        await engine.dispose()
