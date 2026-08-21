import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.identity import (
    CreateAthleteAccountLinkInviteCommand,
    CreateAthleteAccountLinkInviteInteractor,
    LinkAthleteAccountCommand,
    LinkAthleteAccountInteractor,
    LinkAthleteAccountResult,
    ListUnlinkedAthletesInteractor,
    ListUnlinkedAthletesQuery,
)
from application.identity.errors import (
    AthleteAlreadyLinkedError,
    InvalidBotInviteError,
)
from domain.identity import BotInvitePurpose, SystemRoleCode
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

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class StaticTokenGenerator:
    def __init__(self, token: str) -> None:
        self._token = token

    def generate(self) -> str:
        return self._token


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


async def create_administrator_and_athlete(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int]:
    telegram_id = 7_000_000 + uuid4().int % 1_000_000_000
    async with session_factory.begin() as session:
        admin_role = await session.scalar(
            select(RoleModel).where(
                RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
            )
        )
        assert admin_role is not None
        administrator = UserModel(
            telegram_id=telegram_id,
            username="account_link_admin",
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
                role_id=admin_role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )
        athlete = AthleteModel(
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            phone="+79990000000",
            is_active=True,
        )
        session.add(athlete)
        await session.flush()
        athlete_count = await session.scalar(
            select(func.count()).select_from(AthleteModel)
        )
    assert athlete_count is not None
    return telegram_id, athlete.id, athlete_count


async def create_link_invite(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_telegram_id: int,
    athlete_id: int,
    raw_token: str,
    hasher: Sha256InviteTokenHasher,
) -> int:
    async with session_factory() as session:
        interactor = CreateAthleteAccountLinkInviteInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            bot_invite_repository=SqlAlchemyBotInviteRepository(session),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            token_generator=StaticTokenGenerator(raw_token),
            token_hasher=hasher,
        )
        result = await interactor(
            CreateAthleteAccountLinkInviteCommand(
                actor_telegram_id=actor_telegram_id,
                athlete_id=athlete_id,
            )
        )
    assert result.raw_token == raw_token
    return result.invite_id


async def link_account(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    raw_token: str,
    telegram_id: int,
    hasher: Sha256InviteTokenHasher,
    audit_repository: object | None = None,
) -> LinkAthleteAccountResult:
    async with session_factory() as session:
        interactor = LinkAthleteAccountInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            bot_invite_repository=SqlAlchemyBotInviteRepository(session),
            audit_log_repository=(
                audit_repository  # type: ignore[arg-type]
                if audit_repository is not None
                else SqlAlchemyAuditLogRepository(session)
            ),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
            token_hasher=hasher,
        )
        return await interactor(
            LinkAthleteAccountCommand(
                telegram_id=telegram_id,
                username=f"linked_{telegram_id}",
                first_name="Telegram",
                last_name="Athlete",
                invite_token=raw_token,
            )
        )


async def test_personal_invite_links_existing_athlete_once(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    hasher = Sha256InviteTokenHasher()
    raw_token = f"opaque-{uuid4()}"
    linked_telegram_id = 8_000_000 + uuid4().int % 1_000_000_000
    try:
        await ensure_system_roles(session_factory)
        admin_telegram_id, athlete_id, athlete_count_before = (
            await create_administrator_and_athlete(session_factory)
        )

        async with session_factory() as session:
            listed = await ListUnlinkedAthletesInteractor(
                SqlAlchemyUserRepository(session),
                SqlAlchemyAthleteRepository(session),
                SqlAlchemyRoleRepository(session),
            )(
                ListUnlinkedAthletesQuery(
                    actor_telegram_id=admin_telegram_id
                )
            )
        assert athlete_id in {item.athlete_id for item in listed}

        invite_id = await create_link_invite(
            session_factory,
            actor_telegram_id=admin_telegram_id,
            athlete_id=athlete_id,
            raw_token=raw_token,
            hasher=hasher,
        )

        async with session_factory() as session:
            invite = await session.get(BotInviteModel, invite_id)
            assert invite is not None
            assert invite.token_hash == hasher.hash(raw_token)
            assert invite.token_hash != raw_token
            assert invite.purpose is BotInvitePurpose.ATHLETE_LINK
            assert invite.athlete_id == athlete_id
            assert invite.consumed_at is None

        result = await link_account(
            session_factory,
            raw_token=raw_token,
            telegram_id=linked_telegram_id,
            hasher=hasher,
        )
        assert result.athlete_id == athlete_id

        async with session_factory() as session:
            athlete = await session.get(AthleteModel, athlete_id)
            invite = await session.get(BotInviteModel, invite_id)
            linked_user = await session.scalar(
                select(UserModel).where(
                    UserModel.telegram_id == linked_telegram_id
                )
            )
            athlete_count_after = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )
            assert athlete is not None
            assert invite is not None
            assert linked_user is not None
            role_code = await session.scalar(
                select(RoleModel.code)
                .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
                .where(UserRoleModel.user_id == linked_user.id)
            )
            link_audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ATHLETE_ACCOUNT_LINKED",
                    AuditLogModel.entity_id == athlete_id,
                )
            )

        assert athlete.user_id == linked_user.id
        assert athlete_count_after == athlete_count_before
        assert invite.consumed_at == NOW
        assert role_code == SystemRoleCode.ATHLETE.value
        assert link_audit is not None
        assert link_audit.actor_user_id == linked_user.id

        with pytest.raises(InvalidBotInviteError):
            await link_account(
                session_factory,
                raw_token=raw_token,
                telegram_id=linked_telegram_id + 1,
                hasher=hasher,
            )

        async with session_factory() as session:
            duplicate_user = await session.scalar(
                select(UserModel).where(
                    UserModel.telegram_id == linked_telegram_id + 1
                )
            )
        assert duplicate_user is None
    finally:
        await engine.dispose()


async def test_concurrent_invites_cannot_link_two_users_to_one_athlete(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    hasher = Sha256InviteTokenHasher()
    first_token = f"opaque-first-{uuid4()}"
    second_token = f"opaque-second-{uuid4()}"
    first_telegram_id = 9_000_000 + uuid4().int % 100_000_000
    second_telegram_id = 10_000_000 + uuid4().int % 100_000_000
    try:
        await ensure_system_roles(session_factory)
        admin_telegram_id, athlete_id, _ = (
            await create_administrator_and_athlete(session_factory)
        )
        await create_link_invite(
            session_factory,
            actor_telegram_id=admin_telegram_id,
            athlete_id=athlete_id,
            raw_token=first_token,
            hasher=hasher,
        )
        await create_link_invite(
            session_factory,
            actor_telegram_id=admin_telegram_id,
            athlete_id=athlete_id,
            raw_token=second_token,
            hasher=hasher,
        )

        outcomes = await asyncio.gather(
            link_account(
                session_factory,
                raw_token=first_token,
                telegram_id=first_telegram_id,
                hasher=hasher,
            ),
            link_account(
                session_factory,
                raw_token=second_token,
                telegram_id=second_telegram_id,
                hasher=hasher,
            ),
            return_exceptions=True,
        )

        assert sum(isinstance(item, LinkAthleteAccountResult) for item in outcomes) == 1
        assert sum(isinstance(item, AthleteAlreadyLinkedError) for item in outcomes) == 1

        async with session_factory() as session:
            athlete = await session.get(AthleteModel, athlete_id)
            linked_users = (
                await session.scalars(
                    select(UserModel).where(
                        UserModel.telegram_id.in_(
                            (first_telegram_id, second_telegram_id)
                        )
                    )
                )
            ).all()
            consumed_count = await session.scalar(
                select(func.count())
                .select_from(BotInviteModel)
                .where(
                    BotInviteModel.athlete_id == athlete_id,
                    BotInviteModel.consumed_at.is_not(None),
                )
            )

        assert athlete is not None
        assert len(linked_users) == 1
        assert athlete.user_id == linked_users[0].id
        assert consumed_count == 1
    finally:
        await engine.dispose()


async def test_link_transaction_rolls_back_user_role_link_and_consume(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    hasher = Sha256InviteTokenHasher()
    raw_token = f"opaque-rollback-{uuid4()}"
    telegram_id = 11_000_000 + uuid4().int % 100_000_000
    try:
        await ensure_system_roles(session_factory)
        admin_telegram_id, athlete_id, _ = (
            await create_administrator_and_athlete(session_factory)
        )
        invite_id = await create_link_invite(
            session_factory,
            actor_telegram_id=admin_telegram_id,
            athlete_id=athlete_id,
            raw_token=raw_token,
            hasher=hasher,
        )

        with pytest.raises(RuntimeError, match="audit persistence failed"):
            await link_account(
                session_factory,
                raw_token=raw_token,
                telegram_id=telegram_id,
                hasher=hasher,
                audit_repository=FailingAuditLogRepository(),
            )

        async with session_factory() as session:
            athlete = await session.get(AthleteModel, athlete_id)
            invite = await session.get(BotInviteModel, invite_id)
            linked_user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id)
            )

        assert athlete is not None
        assert invite is not None
        assert athlete.user_id is None
        assert invite.consumed_at is None
        assert linked_user is None
    finally:
        await engine.dispose()
