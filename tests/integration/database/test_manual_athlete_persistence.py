"""PostgreSQL coverage for manual Athlete creation."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.athletes import (
    CreateManualAthleteCommand,
    CreateManualAthleteInteractor,
)
from application.identity import (
    ListUnlinkedAthletesInteractor,
    ListUnlinkedAthletesQuery,
)
from domain.identity import SystemRoleCode
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    BotInviteModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.system_roles import ensure_system_roles
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
BIRTH_DATE = date(1993, 8, 25)


class FailingAuditLogRepository:
    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
    ) -> None:
        del actor_user_id, action, entity_type, entity_id
        raise RuntimeError("audit persistence failed")


async def create_administrator(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    telegram_id = 15_000_000 + uuid4().int % 1_000_000_000
    async with session_factory.begin() as session:
        role = await session.scalar(
            select(RoleModel).where(
                RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
            )
        )
        assert role is not None
        administrator = UserModel(
            telegram_id=telegram_id,
            username=f"manual_athlete_admin_{telegram_id}",
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(administrator)
        await session.flush()
        session.add(
            UserRoleModel(
                user_id=administrator.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )
    return telegram_id, administrator.id


async def persistence_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, int, int]:
    async with session_factory() as session:
        values = (
            await session.scalar(select(func.count()).select_from(UserModel)),
            await session.scalar(
                select(func.count()).select_from(UserRoleModel)
            ),
            await session.scalar(
                select(func.count()).select_from(BotInviteModel)
            ),
            await session.scalar(
                select(func.count()).select_from(AthleteModel)
            ),
            await session.scalar(
                select(func.count()).select_from(AuditLogModel)
            ),
        )
    assert all(value is not None for value in values)
    return tuple(int(value) for value in values)  # type: ignore[arg-type,return-value]


async def create_manual_athlete(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_telegram_id: int,
    first_name: str,
    last_name: str = "Иванова",
    birth_date: date = BIRTH_DATE,
    audit_repository: object | None = None,
) -> None:
    async with session_factory() as session:
        interactor = CreateManualAthleteInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            audit_log_repository=(
                audit_repository  # type: ignore[arg-type]
                if audit_repository is not None
                else SqlAlchemyAuditLogRepository(session)
            ),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        )
        await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=actor_telegram_id,
                first_name=first_name,
                last_name=last_name,
                birth_date=birth_date,
            )
        )


async def test_manual_athlete_is_persisted_unlinked_and_listed(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    first_name = f"Manual-{uuid4()}"
    try:
        await ensure_system_roles(session_factory)
        actor_telegram_id, actor_user_id = await create_administrator(
            session_factory
        )
        counts_before = await persistence_counts(session_factory)

        await create_manual_athlete(
            session_factory,
            actor_telegram_id=actor_telegram_id,
            first_name=first_name,
        )

        counts_after = await persistence_counts(session_factory)
        assert counts_after[:3] == counts_before[:3]
        assert counts_after[3] == counts_before[3] + 1
        assert counts_after[4] == counts_before[4] + 1

        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
            assert athlete is not None
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.entity_id == athlete.id,
                )
            )
            listed = await ListUnlinkedAthletesInteractor(
                SqlAlchemyUserRepository(session),
                SqlAlchemyAthleteRepository(session),
                SqlAlchemyRoleRepository(session),
            )(
                ListUnlinkedAthletesQuery(
                    actor_telegram_id=actor_telegram_id
                )
            )
            resolved_by_public_id = await SqlAlchemyAthleteRepository(
                session
            ).get_by_public_id(athlete.athlete_public_id)

        assert athlete.user_id is None
        assert athlete.athlete_public_id.version == 4
        assert athlete.last_name == "Иванова"
        assert athlete.birth_date == BIRTH_DATE
        assert athlete.phone is None
        assert athlete.is_active
        assert audit is not None
        assert audit.actor_user_id == actor_user_id
        assert audit.entity_type == "ATHLETE"
        assert audit.created_at is not None
        assert athlete.id in {item.athlete_id for item in listed}
        assert resolved_by_public_id is not None
        assert resolved_by_public_id.id == athlete.id
        assert (
            resolved_by_public_id.athlete_public_id
            == athlete.athlete_public_id
        )
    finally:
        await engine.dispose()


async def test_equal_athlete_names_are_persisted_separately(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    first_name = f"Duplicate-{uuid4()}"
    try:
        await ensure_system_roles(session_factory)
        actor_telegram_id, _ = await create_administrator(session_factory)

        await create_manual_athlete(
            session_factory,
            actor_telegram_id=actor_telegram_id,
            first_name=first_name,
        )
        await create_manual_athlete(
            session_factory,
            actor_telegram_id=actor_telegram_id,
            first_name=first_name,
        )

        async with session_factory() as session:
            athlete_count = await session.scalar(
                select(func.count())
                .select_from(AthleteModel)
                .where(AthleteModel.first_name == first_name)
            )
        assert athlete_count == 2
    finally:
        await engine.dispose()


async def test_audit_failure_rolls_back_manual_athlete(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    first_name = f"Rollback-{uuid4()}"
    try:
        await ensure_system_roles(session_factory)
        actor_telegram_id, _ = await create_administrator(session_factory)
        counts_before = await persistence_counts(session_factory)

        with pytest.raises(RuntimeError, match="audit persistence failed"):
            await create_manual_athlete(
                session_factory,
                actor_telegram_id=actor_telegram_id,
                first_name=first_name,
                audit_repository=FailingAuditLogRepository(),
            )

        counts_after = await persistence_counts(session_factory)
        assert counts_after == counts_before
        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
        assert athlete is None
    finally:
        await engine.dispose()
