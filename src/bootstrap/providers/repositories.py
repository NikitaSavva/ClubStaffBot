from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from application.club import TrainingGroupReader, TrainingGroupRepository
from application.common import UnitOfWork
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    BotInviteRepository,
    BotUserReader,
    RoleRepository,
    UserRepository,
)
from application.training_sessions import (
    ScheduleRuleRepository,
    TrainingSessionRepository,
)
from infrastructure.database.readers import (
    SqlAlchemyBotUserReader,
    SqlAlchemyTrainingGroupReader,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyBotInviteRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyScheduleRuleRepository,
    SqlAlchemyTrainingGroupRepository,
    SqlAlchemyTrainingSessionRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class RepositoryProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_schedule_rule_repository(
        self,
        session: AsyncSession,
    ) -> ScheduleRuleRepository:
        return SqlAlchemyScheduleRuleRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_training_session_repository(
        self,
        session: AsyncSession,
    ) -> TrainingSessionRepository:
        return SqlAlchemyTrainingSessionRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_training_group_reader(
        self,
        session: AsyncSession,
    ) -> TrainingGroupReader:
        return SqlAlchemyTrainingGroupReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_training_group_repository(
        self,
        session: AsyncSession,
    ) -> TrainingGroupRepository:
        return SqlAlchemyTrainingGroupRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_bot_user_reader(
        self,
        session: AsyncSession,
    ) -> BotUserReader:
        return SqlAlchemyBotUserReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_athlete_repository(
        self,
        session: AsyncSession,
    ) -> AthleteRepository:
        return SqlAlchemyAthleteRepository(session)

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
