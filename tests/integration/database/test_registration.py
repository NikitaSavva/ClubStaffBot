from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from application.identity import (
    LinkAthleteAccountInteractor,
    RegisterBotUserCommand,
    RegisterBotUserInteractor,
)
from application.identity.errors import UserAlreadyRegisteredError
from domain.identity import Athlete, SystemRoleCode, User
from infrastructure.database.development_invites import create_development_invite
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
    SqlAlchemyBotInviteRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.system_roles import ensure_system_roles
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.security import Sha256InviteTokenHasher

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FailingAthleteRepository:
    async def add(self, athlete: Athlete) -> int:
        del athlete
        raise RuntimeError("athlete persistence failed")


def build_link_interactor(
    session: AsyncSession,
    hasher: Sha256InviteTokenHasher,
) -> LinkAthleteAccountInteractor:
    return LinkAthleteAccountInteractor(
        user_repository=SqlAlchemyUserRepository(session),
        athlete_repository=SqlAlchemyAthleteRepository(session),
        role_repository=SqlAlchemyRoleRepository(session),
        bot_invite_repository=SqlAlchemyBotInviteRepository(session),
        audit_log_repository=SqlAlchemyAuditLogRepository(session),
        unit_of_work=SqlAlchemyUnitOfWork(session),
        clock=FrozenClock(),
        token_hasher=hasher,
    )


async def test_system_role_bootstrap_is_idempotent(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        await ensure_system_roles(session_factory)
        await ensure_system_roles(session_factory)

        async with session_factory() as session:
            roles = (
                await session.scalars(
                    select(RoleModel).where(
                        RoleModel.code.in_(
                            code.value for code in SystemRoleCode
                        )
                    )
                )
            ).all()

        assert {role.code for role in roles} == {
            code.value for code in SystemRoleCode
        }
        assert len(roles) == len(SystemRoleCode)
        assert all(role.is_system and role.is_active for role in roles)
    finally:
        await engine.dispose()


async def test_development_invite_registers_user_in_one_transaction(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    hasher = Sha256InviteTokenHasher()
    telegram_id = 1_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        first_token = await create_development_invite(session_factory, hasher)
        second_token = await create_development_invite(session_factory, hasher)

        assert first_token != second_token
        async with session_factory() as session:
            stored_hashes = set(
                await session.scalars(select(BotInviteModel.token_hash))
            )
        assert hasher.hash(first_token) in stored_hashes
        assert hasher.hash(second_token) in stored_hashes
        assert first_token not in stored_hashes
        assert second_token not in stored_hashes

        async with session_factory() as session:
            interactor = RegisterBotUserInteractor(
                user_repository=SqlAlchemyUserRepository(session),
                athlete_repository=SqlAlchemyAthleteRepository(session),
                role_repository=SqlAlchemyRoleRepository(session),
                bot_invite_repository=SqlAlchemyBotInviteRepository(session),
                audit_log_repository=SqlAlchemyAuditLogRepository(session),
                unit_of_work=SqlAlchemyUnitOfWork(session),
                clock=FrozenClock(),
                token_hasher=hasher,
                link_athlete_account_interactor=build_link_interactor(
                    session,
                    hasher,
                ),
            )
            result = await interactor(
                RegisterBotUserCommand(
                    telegram_id=telegram_id,
                    username="integration_user",
                    first_name="Integration",
                    last_name=None,
                    invite_token=first_token,
                )
            )

        async with session_factory() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id)
            )
            assert user is not None
            role_code = await session.scalar(
                select(RoleModel.code)
                .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
                .where(UserRoleModel.user_id == user.id)
            )
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.entity_id == user.id,
                    AuditLogModel.action == "USER_REGISTERED",
                )
            )
            athlete = await session.scalar(
                select(AthleteModel).where(AthleteModel.user_id == user.id)
            )

        assert result.user_id == user.id
        assert role_code == SystemRoleCode.ATHLETE.value
        assert audit is not None
        assert audit.actor_user_id == user.id
        assert athlete is not None
        assert athlete.user_id == user.id
        assert athlete.athlete_public_id.version == 4
        assert athlete.first_name == "Integration"
        assert athlete.last_name is None
        assert athlete.birth_date is None
        assert athlete.phone is None
        assert athlete.is_active

        async with session_factory() as session:
            duplicate_interactor = RegisterBotUserInteractor(
                user_repository=SqlAlchemyUserRepository(session),
                athlete_repository=SqlAlchemyAthleteRepository(session),
                role_repository=SqlAlchemyRoleRepository(session),
                bot_invite_repository=SqlAlchemyBotInviteRepository(session),
                audit_log_repository=SqlAlchemyAuditLogRepository(session),
                unit_of_work=SqlAlchemyUnitOfWork(session),
                clock=FrozenClock(),
                token_hasher=hasher,
                link_athlete_account_interactor=build_link_interactor(
                    session,
                    hasher,
                ),
            )
            with pytest.raises(UserAlreadyRegisteredError):
                await duplicate_interactor(
                    RegisterBotUserCommand(
                        telegram_id=telegram_id,
                        username="integration_user",
                        first_name="Integration",
                        last_name=None,
                        invite_token=first_token,
                    )
                )

        async with session_factory() as session:
            athlete_repository = SqlAlchemyAthleteRepository(session)
            with pytest.raises(IntegrityError):
                async with SqlAlchemyUnitOfWork(session):
                    await athlete_repository.add(
                        Athlete.create_for_registered_user(
                            user_id=result.user_id,
                            first_name="Duplicate",
                            last_name="Athlete",
                        )
                    )

        async with session_factory() as session:
            repository = SqlAlchemyUserRepository(session)
            with pytest.raises(UserAlreadyRegisteredError):
                async with SqlAlchemyUnitOfWork(session):
                    await repository.add(
                        User(
                            id=None,
                            telegram_id=telegram_id,
                            username="race",
                            first_name="Race",
                            last_name="User",
                            is_active=True,
                            registered_at=NOW,
                            last_seen_at=NOW,
                        )
                    )

        async with session_factory() as session:
            user_count = await session.scalar(
                select(func.count()).select_from(UserModel).where(
                    UserModel.telegram_id == telegram_id
                )
            )
            audit_count = await session.scalar(
                select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.entity_id == result.user_id,
                    AuditLogModel.action == "USER_REGISTERED",
                )
            )
            athlete_count = await session.scalar(
                select(func.count()).select_from(AthleteModel).where(
                    AthleteModel.user_id == result.user_id
                )
            )
        assert user_count == 1
        assert audit_count == 1
        assert athlete_count == 1
    finally:
        await engine.dispose()


async def test_registration_rolls_back_when_athlete_creation_fails(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    hasher = Sha256InviteTokenHasher()
    telegram_id = 5_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        raw_token = await create_development_invite(session_factory, hasher)

        async with session_factory() as session:
            counts_before = (
                await session.scalar(
                    select(func.count()).select_from(UserModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(UserRoleModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(AthleteModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(AuditLogModel)
                ),
            )

        async with session_factory() as session:
            interactor = RegisterBotUserInteractor(
                user_repository=SqlAlchemyUserRepository(session),
                athlete_repository=FailingAthleteRepository(),
                role_repository=SqlAlchemyRoleRepository(session),
                bot_invite_repository=SqlAlchemyBotInviteRepository(session),
                audit_log_repository=SqlAlchemyAuditLogRepository(session),
                unit_of_work=SqlAlchemyUnitOfWork(session),
                clock=FrozenClock(),
                token_hasher=hasher,
                link_athlete_account_interactor=build_link_interactor(
                    session,
                    hasher,
                ),
            )
            with pytest.raises(
                RuntimeError,
                match="athlete persistence failed",
            ):
                await interactor(
                    RegisterBotUserCommand(
                        telegram_id=telegram_id,
                        username="rollback_athlete",
                        first_name="Rollback",
                        last_name="Athlete",
                        invite_token=raw_token,
                    )
                )

        async with session_factory() as session:
            stored_user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id)
            )
            counts_after = (
                await session.scalar(
                    select(func.count()).select_from(UserModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(UserRoleModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(AthleteModel)
                ),
                await session.scalar(
                    select(func.count()).select_from(AuditLogModel)
                ),
            )

        assert stored_user is None
        assert counts_after == counts_before
    finally:
        await engine.dispose()


async def test_uow_rolls_back_when_exiting_without_commit(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    telegram_id = 2_000_000 + uuid4().int % 1_000_000_000
    try:
        async with session_factory() as session:
            repository = SqlAlchemyUserRepository(session)
            async with SqlAlchemyUnitOfWork(session):
                await repository.add(
                    User(
                        id=None,
                        telegram_id=telegram_id,
                        username=None,
                        first_name="Rollback",
                        last_name="User",
                        is_active=True,
                        registered_at=NOW,
                        last_seen_at=NOW,
                    )
                )

        async with session_factory() as session:
            stored_user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id)
            )
        assert stored_user is None
    finally:
        await engine.dispose()
