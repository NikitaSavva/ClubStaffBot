from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from application.athletes import CreateManualAthleteInteractor
from application.common import UnitOfWork
from application.identity import (
    AssignOwnerInteractor,
    AssignUserRoleInteractor,
    CreateAthleteAccountLinkInviteInteractor,
    GetUserMenuContextInteractor,
    LinkAthleteAccountInteractor,
    ListUnlinkedAthletesInteractor,
    RegisterBotUserInteractor,
    RemoveUserRoleInteractor,
    SearchBotUsersInteractor,
)
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    BotInviteRepository,
    BotUserReader,
    InviteTokenGenerator,
    InviteTokenHasher,
    RoleRepository,
    UserRepository,
)
from bootstrap.config import Settings
from bootstrap.container import create_container
from infrastructure.database.readers import SqlAlchemyBotUserReader
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyBotInviteRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from presentation.telegram.screen import TelegramScreenRenderer


@pytest.fixture
def settings() -> Settings:
    return Settings(
        postgres_host="database",
        postgres_port=5432,
        postgres_db="staff_bot",
        postgres_user="user",
        postgres_password="password",
        redis_host="cache",
        redis_port=6379,
        redis_db=0,
        telegram_bot_token="123456789:test-token",
        admin_panel_banner_file_id="admin-banner-file-id",
        trainer_panel_banner_file_id="trainer-banner-file-id",
        athlete_panel_banner_file_id="athlete-banner-file-id",
        role_selector_banner_file_id="role-selector-banner-file-id",
        _env_file=None,
    )


async def test_container_resolves_app_and_request_dependencies(
    settings: Settings,
) -> None:
    with (
        patch.object(AsyncEngine, "dispose", new_callable=AsyncMock) as dispose,
        patch.object(AsyncSession, "close", new_callable=AsyncMock) as close_session,
        patch.object(Redis, "aclose", new_callable=AsyncMock) as close_redis,
    ):
        container = create_container(settings)
        resolved_settings = await container.get(Settings)
        engine = await container.get(AsyncEngine)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        redis = await container.get(Redis)
        screen_renderer = await container.get(TelegramScreenRenderer)

        async with container() as request_container:
            first_session = await request_container.get(AsyncSession)
            second_session = await request_container.get(AsyncSession)
            assert first_session is second_session
            user_repository = await request_container.get(UserRepository)
            athlete_repository = await request_container.get(AthleteRepository)
            role_repository = await request_container.get(RoleRepository)
            invite_repository = await request_container.get(
                BotInviteRepository
            )
            bot_user_reader = await request_container.get(BotUserReader)
            audit_repository = await request_container.get(
                AuditLogRepository
            )
            unit_of_work = await request_container.get(UnitOfWork)
            registration_interactor = await request_container.get(
                RegisterBotUserInteractor
            )
            create_manual_athlete_interactor = await request_container.get(
                CreateManualAthleteInteractor
            )
            menu_interactor = await request_container.get(
                GetUserMenuContextInteractor
            )
            list_unlinked_interactor = await request_container.get(
                ListUnlinkedAthletesInteractor
            )
            create_link_invite_interactor = await request_container.get(
                CreateAthleteAccountLinkInviteInteractor
            )
            link_account_interactor = await request_container.get(
                LinkAthleteAccountInteractor
            )
            search_bot_users_interactor = await request_container.get(
                SearchBotUsersInteractor
            )
            assign_user_role_interactor = await request_container.get(
                AssignUserRoleInteractor
            )
            assign_owner_interactor = await request_container.get(
                AssignOwnerInteractor
            )
            remove_user_role_interactor = await request_container.get(
                RemoveUserRoleInteractor
            )

            assert isinstance(user_repository, SqlAlchemyUserRepository)
            assert isinstance(athlete_repository, SqlAlchemyAthleteRepository)
            assert isinstance(role_repository, SqlAlchemyRoleRepository)
            assert isinstance(invite_repository, SqlAlchemyBotInviteRepository)
            assert isinstance(bot_user_reader, SqlAlchemyBotUserReader)
            assert isinstance(audit_repository, SqlAlchemyAuditLogRepository)
            assert isinstance(unit_of_work, SqlAlchemyUnitOfWork)
            assert isinstance(
                registration_interactor,
                RegisterBotUserInteractor,
            )
            assert isinstance(
                create_manual_athlete_interactor,
                CreateManualAthleteInteractor,
            )
            assert isinstance(menu_interactor, GetUserMenuContextInteractor)
            assert isinstance(
                list_unlinked_interactor,
                ListUnlinkedAthletesInteractor,
            )
            assert isinstance(
                create_link_invite_interactor,
                CreateAthleteAccountLinkInviteInteractor,
            )
            assert isinstance(
                link_account_interactor,
                LinkAthleteAccountInteractor,
            )
            assert isinstance(
                search_bot_users_interactor,
                SearchBotUsersInteractor,
            )
            assert isinstance(
                assign_user_role_interactor,
                AssignUserRoleInteractor,
            )
            assert isinstance(assign_owner_interactor, AssignOwnerInteractor)
            assert isinstance(
                remove_user_role_interactor,
                RemoveUserRoleInteractor,
            )
            assert user_repository._session is first_session
            assert athlete_repository._session is first_session
            assert role_repository._session is first_session
            assert invite_repository._session is first_session
            assert bot_user_reader._session is first_session
            assert audit_repository._session is first_session
            assert unit_of_work._session is first_session
            assert menu_interactor._users is user_repository
            assert menu_interactor._roles is role_repository
            assert create_manual_athlete_interactor._users is user_repository
            assert (
                create_manual_athlete_interactor._athletes
                is athlete_repository
            )
            assert (
                create_manual_athlete_interactor._audit_log
                is audit_repository
            )
            assert link_account_interactor._users is user_repository
            assert link_account_interactor._athletes is athlete_repository
            assert link_account_interactor._invites is invite_repository
            assert registration_interactor._link_athlete_account is (
                link_account_interactor
            )
            assert search_bot_users_interactor._reader is bot_user_reader
            assert assign_user_role_interactor._users is user_repository
            assert assign_user_role_interactor._roles is role_repository
            assert (
                assign_user_role_interactor._audit_log is audit_repository
            )
            assert assign_owner_interactor._users is user_repository
            assert assign_owner_interactor._roles is role_repository
            assert assign_owner_interactor._audit_log is audit_repository
            assert remove_user_role_interactor._users is user_repository
            assert remove_user_role_interactor._roles is role_repository
            assert remove_user_role_interactor._audit_log is audit_repository

        token_hasher = await container.get(InviteTokenHasher)
        token_generator = await container.get(InviteTokenGenerator)
        assert len(token_hasher.hash("test-token")) == 64
        assert len(token_generator.generate()) >= 32

        await container.close()

        assert resolved_settings is settings
        assert session_factory.kw["bind"] is engine
        assert redis.connection_pool.connection_kwargs["host"] == "cache"
        assert screen_renderer._bot.id == 123456789
        close_session.assert_awaited_once()
        dispose.assert_awaited_once()
        close_redis.assert_awaited_once()
