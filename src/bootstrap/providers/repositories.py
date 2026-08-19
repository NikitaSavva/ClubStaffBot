from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from application.common import UnitOfWork
from application.identity.ports import (
    AuditLogRepository,
    BotInviteRepository,
    RoleRepository,
    UserRepository,
)
from infrastructure.database.repositories import (
    SqlAlchemyAuditLogRepository,
    SqlAlchemyBotInviteRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class RepositoryProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_user_repository(
        self,
        session: AsyncSession,
    ) -> UserRepository:
        return SqlAlchemyUserRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_role_repository(
        self,
        session: AsyncSession,
    ) -> RoleRepository:
        return SqlAlchemyRoleRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_bot_invite_repository(
        self,
        session: AsyncSession,
    ) -> BotInviteRepository:
        return SqlAlchemyBotInviteRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_audit_log_repository(
        self,
        session: AsyncSession,
    ) -> AuditLogRepository:
        return SqlAlchemyAuditLogRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_unit_of_work(self, session: AsyncSession) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session)
