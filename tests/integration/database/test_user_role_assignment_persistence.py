from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.identity import (
    AssignUserRoleCommand,
    AssignUserRoleInteractor,
    RemoveUserRoleCommand,
    RemoveUserRoleInteractor,
    SearchBotUsersInteractor,
    SearchBotUsersQuery,
)
from application.identity.errors import LastUserRoleRemovalForbiddenError
from domain.identity import SystemRoleCode
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.readers import SqlAlchemyBotUserReader
from infrastructure.database.repositories import (
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.system_roles import ensure_system_roles
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class AuditThenFailRepository:
    def __init__(self, repository: SqlAlchemyAuditLogRepository) -> None:
        self._repository = repository

    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
        payload: dict[str, object] | None = None,
    ) -> None:
        await self._repository.add(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        raise RuntimeError("audit persistence failed")


async def add_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str,
    last_name: str,
) -> UserModel:
    user = UserModel(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    return user


async def role_by_code(
    session: AsyncSession,
    role_code: SystemRoleCode,
) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(RoleModel.code == role_code.value)
    )
    assert role is not None
    return role


async def assign_role(
    session: AsyncSession,
    *,
    user_id: int,
    role_code: SystemRoleCode,
    assigned_by_user_id: int | None = None,
) -> None:
    role = await role_by_code(session, role_code)
    session.add(
        UserRoleModel(
            user_id=user_id,
            role_id=role.id,
            assigned_by_user_id=assigned_by_user_id,
            assigned_at=NOW,
        )
    )


async def create_actor_and_target(
    session: AsyncSession,
) -> tuple[UserModel, UserModel]:
    suffix = uuid4().hex[:10]
    actor = await add_user(
        session,
        telegram_id=21_000_000 + uuid4().int % 1_000_000_000,
        username=f"admin_{suffix}",
        first_name="Admin",
        last_name=suffix,
    )
    target = await add_user(
        session,
        telegram_id=22_000_000 + uuid4().int % 1_000_000_000,
        username=f"target_{suffix}",
        first_name=f"Мария{suffix}",
        last_name=f"Петрова{suffix}",
    )
    await assign_role(
        session,
        user_id=actor.id,
        role_code=SystemRoleCode.ADMINISTRATOR,
    )
    await assign_role(
        session,
        user_id=target.id,
        role_code=SystemRoleCode.ATHLETE,
    )
    return actor, target


def build_assign_interactor(
    session: AsyncSession,
    *,
    failing_audit: bool = False,
) -> AssignUserRoleInteractor:
    audit_repository = SqlAlchemyAuditLogRepository(session)
    return AssignUserRoleInteractor(
        user_repository=SqlAlchemyUserRepository(session),
        role_repository=SqlAlchemyRoleRepository(session),
        audit_log_repository=(
            AuditThenFailRepository(audit_repository)
            if failing_audit
            else audit_repository
        ),
        unit_of_work=SqlAlchemyUnitOfWork(session),
        clock=FrozenClock(),
    )


def build_remove_interactor(
    session: AsyncSession,
    *,
    failing_audit: bool = False,
) -> RemoveUserRoleInteractor:
    audit_repository = SqlAlchemyAuditLogRepository(session)
    return RemoveUserRoleInteractor(
        user_repository=SqlAlchemyUserRepository(session),
        role_repository=SqlAlchemyRoleRepository(session),
        audit_log_repository=(
            AuditThenFailRepository(audit_repository)
            if failing_audit
            else audit_repository
        ),
        unit_of_work=SqlAlchemyUnitOfWork(session),
    )


async def test_search_bot_users_reads_names_username_and_current_roles(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor, target = await create_actor_and_target(session)
            await assign_role(
                session,
                user_id=target.id,
                role_code=SystemRoleCode.TRAINER,
                assigned_by_user_id=actor.id,
            )

        queries = (
            target.first_name,
            target.last_name,
            f"@{target.username}",
        )
        for query in queries:
            async with session_factory() as session:
                interactor = SearchBotUsersInteractor(
                    user_repository=SqlAlchemyUserRepository(session),
                    role_repository=SqlAlchemyRoleRepository(session),
                    bot_user_reader=SqlAlchemyBotUserReader(session),
                )
                result = await interactor(
                    SearchBotUsersQuery(
                        actor_telegram_id=actor.telegram_id,
                        query=query,
                    )
                )

            assert len(result.users) == 1
            found_user = result.users[0]
            assert found_user.user_id == target.id
            assert found_user.first_name == target.first_name
            assert found_user.last_name == target.last_name
            assert found_user.username == target.username
            assert found_user.role_codes == (
                SystemRoleCode.ATHLETE,
                SystemRoleCode.TRAINER,
            )
            assert type(found_user).__module__ == "application.identity.dto"
    finally:
        await engine.dispose()


async def test_assignment_persists_additional_role_and_audit_idempotently(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor, target = await create_actor_and_target(session)

        command = AssignUserRoleCommand(
            actor_telegram_id=actor.telegram_id,
            target_user_id=target.id,
            role_code=SystemRoleCode.TRAINER,
        )
        async with session_factory() as session:
            first_result = await build_assign_interactor(session)(command)
        async with session_factory() as session:
            repeated_result = await build_assign_interactor(session)(command)

        assert first_result.role_was_assigned
        assert not repeated_result.role_was_assigned

        async with session_factory() as session:
            role_rows = (
                await session.execute(
                    select(
                        RoleModel.code,
                        UserRoleModel.assigned_by_user_id,
                    )
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == target.id)
                )
            ).all()
            audits = (
                await session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "ROLE_ASSIGNED",
                        AuditLogModel.entity_type == "USER",
                        AuditLogModel.entity_id == target.id,
                    )
                )
            ).all()

        assert {code for code, _ in role_rows} == {
            SystemRoleCode.ATHLETE.value,
            SystemRoleCode.TRAINER.value,
        }
        trainer_assignments = [
            assigned_by_user_id
            for code, assigned_by_user_id in role_rows
            if code == SystemRoleCode.TRAINER.value
        ]
        assert trainer_assignments == [actor.id]
        assert len(audits) == 1
        assert audits[0].actor_user_id == actor.id
        assert audits[0].payload == {"role_code": "TRAINER"}
    finally:
        await engine.dispose()


async def test_assignment_and_audit_roll_back_together(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor, target = await create_actor_and_target(session)

        async with session_factory() as session:
            interactor = build_assign_interactor(
                session,
                failing_audit=True,
            )
            with pytest.raises(
                RuntimeError,
                match="audit persistence failed",
            ):
                await interactor(
                    AssignUserRoleCommand(
                        actor_telegram_id=actor.telegram_id,
                        target_user_id=target.id,
                        role_code=SystemRoleCode.TRAINER,
                    )
                )

        async with session_factory() as session:
            trainer_role = await role_by_code(
                session,
                SystemRoleCode.TRAINER,
            )
            assignment_count = await session.scalar(
                select(func.count())
                .select_from(UserRoleModel)
                .where(
                    UserRoleModel.user_id == target.id,
                    UserRoleModel.role_id == trainer_role.id,
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ROLE_ASSIGNED",
                    AuditLogModel.entity_id == target.id,
                )
            )

        assert assignment_count == 0
        assert audit_count == 0
    finally:
        await engine.dispose()


async def test_role_removal_persists_audit_and_preserves_athlete_link(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor, target = await create_actor_and_target(session)
            await assign_role(
                session,
                user_id=target.id,
                role_code=SystemRoleCode.TRAINER,
                assigned_by_user_id=actor.id,
            )
            athlete = AthleteModel(
                user_id=target.id,
                first_name="Иван",
                last_name="Иванов",
                birth_date=None,
                phone=None,
                is_active=True,
            )
            session.add(athlete)
            await session.flush()
            athlete_id = athlete.id

        command = RemoveUserRoleCommand(
            actor_telegram_id=actor.telegram_id,
            target_user_id=target.id,
            role_code=SystemRoleCode.ATHLETE,
        )
        async with session_factory() as session:
            first_result = await build_remove_interactor(session)(command)
        async with session_factory() as session:
            repeated_result = await build_remove_interactor(session)(command)

        assert first_result.role_was_removed
        assert first_result.current_role_codes == (SystemRoleCode.TRAINER,)
        assert not repeated_result.role_was_removed

        async with session_factory() as session:
            role_codes = set(
                await session.scalars(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == target.id)
                )
            )
            persisted_athlete = await session.get(AthleteModel, athlete_id)
            audits = (
                await session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "ROLE_REMOVED",
                        AuditLogModel.entity_id == target.id,
                    )
                )
            ).all()

        assert role_codes == {SystemRoleCode.TRAINER.value}
        assert persisted_athlete is not None
        assert persisted_athlete.user_id == target.id
        assert len(audits) == 1
        assert audits[0].actor_user_id == actor.id
        assert audits[0].payload == {"role_code": "ATHLETE"}
        assert audits[0].created_at is not None

        async with session_factory() as session:
            with pytest.raises(LastUserRoleRemovalForbiddenError):
                await build_remove_interactor(session)(
                    RemoveUserRoleCommand(
                        actor_telegram_id=actor.telegram_id,
                        target_user_id=target.id,
                        role_code=SystemRoleCode.TRAINER,
                    )
                )
    finally:
        await engine.dispose()


async def test_role_removal_and_audit_roll_back_together(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor, target = await create_actor_and_target(session)
            await assign_role(
                session,
                user_id=target.id,
                role_code=SystemRoleCode.TRAINER,
                assigned_by_user_id=actor.id,
            )

        async with session_factory() as session:
            with pytest.raises(
                RuntimeError,
                match="audit persistence failed",
            ):
                await build_remove_interactor(
                    session,
                    failing_audit=True,
                )(
                    RemoveUserRoleCommand(
                        actor_telegram_id=actor.telegram_id,
                        target_user_id=target.id,
                        role_code=SystemRoleCode.TRAINER,
                    )
                )

        async with session_factory() as session:
            role_codes = set(
                await session.scalars(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == target.id)
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ROLE_REMOVED",
                    AuditLogModel.entity_id == target.id,
                )
            )

        assert role_codes == {"ATHLETE", "TRAINER"}
        assert audit_count == 0
    finally:
        await engine.dispose()
