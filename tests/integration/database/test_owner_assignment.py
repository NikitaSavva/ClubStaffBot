import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.identity import (
    AssignOwnerCommand,
    AssignOwnerInteractor,
    AssignOwnerResult,
)
from application.identity.errors import OwnerAlreadyAssignedError
from domain.identity import SystemRoleCode
from infrastructure.database.models import (
    AuditLogModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.system_roles import ensure_system_roles
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


async def owner_role(session: AsyncSession) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(
            RoleModel.code == SystemRoleCode.OWNER.value
        )
    )
    assert role is not None
    return role


async def reset_owner_assignments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        role = await owner_role(session)
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.role_id == role.id)
        )


async def add_registered_user(
    session: AsyncSession,
    *,
    telegram_id: int,
) -> UserModel:
    suffix = uuid4().hex[:10]
    user = UserModel(
        telegram_id=telegram_id,
        username=f"owner_target_{suffix}",
        first_name="Owner",
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    athlete_role = await session.scalar(
        select(RoleModel).where(
            RoleModel.code == SystemRoleCode.ATHLETE.value
        )
    )
    assert athlete_role is not None
    session.add(
        UserRoleModel(
            user_id=user.id,
            role_id=athlete_role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    return user


async def execute_assignment(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> AssignOwnerResult:
    async with session_factory() as session:
        return await AssignOwnerInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
        )(AssignOwnerCommand(telegram_id=telegram_id))


async def test_owner_assignment_persists_system_audit_idempotently(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    telegram_id = 31_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        await reset_owner_assignments(session_factory)
        async with session_factory.begin() as session:
            target = await add_registered_user(
                session,
                telegram_id=telegram_id,
            )

        first_result = await execute_assignment(session_factory, telegram_id)
        repeated_result = await execute_assignment(
            session_factory,
            telegram_id,
        )

        assert first_result.owner_was_assigned
        assert not repeated_result.owner_was_assigned

        async with session_factory() as session:
            role = await owner_role(session)
            assignments = (
                await session.scalars(
                    select(UserRoleModel).where(
                        UserRoleModel.role_id == role.id
                    )
                )
            ).all()
            audits = (
                await session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "OWNER_ASSIGNED",
                        AuditLogModel.entity_id == target.id,
                    )
                )
            ).all()

        assert len(assignments) == 1
        assert assignments[0].user_id == target.id
        assert assignments[0].assigned_by_user_id is None
        assert len(audits) == 1
        assert audits[0].actor_user_id is None
        assert audits[0].payload == {
            "role_code": "OWNER",
            "source": "OPERATOR_SCRIPT",
        }
        assert audits[0].created_at is not None
    finally:
        await engine.dispose()


async def test_owner_assignment_refuses_second_user_without_transfer(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    first_telegram_id = 32_000_000 + uuid4().int % 1_000_000_000
    second_telegram_id = 33_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        await reset_owner_assignments(session_factory)
        async with session_factory.begin() as session:
            first_user = await add_registered_user(
                session,
                telegram_id=first_telegram_id,
            )
            second_user = await add_registered_user(
                session,
                telegram_id=second_telegram_id,
            )

        await execute_assignment(session_factory, first_telegram_id)

        try:
            await execute_assignment(session_factory, second_telegram_id)
        except OwnerAlreadyAssignedError:
            pass
        else:
            raise AssertionError("Second OWNER assignment must fail")

        async with session_factory() as session:
            role = await owner_role(session)
            owner_user_ids = set(
                await session.scalars(
                    select(UserRoleModel.user_id).where(
                        UserRoleModel.role_id == role.id
                    )
                )
            )

        assert owner_user_ids == {first_user.id}
        assert second_user.id not in owner_user_ids
    finally:
        await engine.dispose()


async def test_concurrent_owner_assignments_create_at_most_one_owner(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    first_telegram_id = 34_000_000 + uuid4().int % 1_000_000_000
    second_telegram_id = 35_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        await reset_owner_assignments(session_factory)
        async with session_factory.begin() as session:
            await add_registered_user(
                session,
                telegram_id=first_telegram_id,
            )
            await add_registered_user(
                session,
                telegram_id=second_telegram_id,
            )

        outcomes = await asyncio.gather(
            execute_assignment(session_factory, first_telegram_id),
            execute_assignment(session_factory, second_telegram_id),
            return_exceptions=True,
        )

        assert sum(
            isinstance(outcome, AssignOwnerResult)
            and outcome.owner_was_assigned
            for outcome in outcomes
        ) == 1
        assert sum(
            isinstance(outcome, OwnerAlreadyAssignedError)
            for outcome in outcomes
        ) == 1

        async with session_factory() as session:
            role = await owner_role(session)
            assignment_count = await session.scalar(
                select(func.count())
                .select_from(UserRoleModel)
                .where(UserRoleModel.role_id == role.id)
            )

        assert assignment_count == 1
    finally:
        await engine.dispose()
