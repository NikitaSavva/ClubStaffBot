from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from application.athletes import AthleteSelectionReader
from application.attendance import (
    AttendanceRepository,
    AttendanceSessionRepository,
)
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
from application.subscriptions import (
    MySubscriptionReader,
    SubscriptionPlanReader,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from application.trainer_notifications import (
    TrainerNotificationDeliveryRepository,
    TrainerNotificationReader,
)
from application.training_sessions import (
    CurrentWeekScheduleReader,
    ScheduleRuleRepository,
    TrainingSessionRepository,
)
from infrastructure.database.readers import (
    SqlAlchemyAthleteSelectionReader,
    SqlAlchemyBotUserReader,
    SqlAlchemyCurrentWeekScheduleReader,
    SqlAlchemyMySubscriptionReader,
    SqlAlchemySubscriptionPlanReader,
    SqlAlchemyTrainingGroupReader,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAttendanceRepository,
    SqlAlchemyAttendanceSessionRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyBotInviteRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyScheduleRuleRepository,
    SqlAlchemySubscriptionPlanRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyTrainingGroupRepository,
    SqlAlchemyTrainingSessionRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.trainer_notifications import (
    SqlAlchemyTrainerNotificationDeliveryRepository,
    SqlAlchemyTrainerNotificationReader,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class RepositoryProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_trainer_notification_reader(
        self,
        session: AsyncSession,
    ) -> TrainerNotificationReader:
        return SqlAlchemyTrainerNotificationReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_trainer_notification_delivery_repository(
        self,
        session: AsyncSession,
    ) -> TrainerNotificationDeliveryRepository:
        return SqlAlchemyTrainerNotificationDeliveryRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_attendance_repository(
        self,
        session: AsyncSession,
    ) -> AttendanceRepository:
        return SqlAlchemyAttendanceRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_attendance_session_repository(
        self,
        session: AsyncSession,
    ) -> AttendanceSessionRepository:
        return SqlAlchemyAttendanceSessionRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_current_week_schedule_reader(
        self,
        session: AsyncSession,
    ) -> CurrentWeekScheduleReader:
        return SqlAlchemyCurrentWeekScheduleReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_my_subscription_reader(
        self,
        session: AsyncSession,
    ) -> MySubscriptionReader:
        return SqlAlchemyMySubscriptionReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_subscription_plan_reader(
        self,
        session: AsyncSession,
    ) -> SubscriptionPlanReader:
        return SqlAlchemySubscriptionPlanReader(session)

    @provide(scope=Scope.REQUEST)
    def provide_subscription_plan_repository(
        self,
        session: AsyncSession,
    ) -> SubscriptionPlanRepository:
        return SqlAlchemySubscriptionPlanRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_subscription_repository(
        self,
        session: AsyncSession,
    ) -> SubscriptionRepository:
        return SqlAlchemySubscriptionRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_athlete_selection_reader(
        self,
        session: AsyncSession,
    ) -> AthleteSelectionReader:
        return SqlAlchemyAthleteSelectionReader(session)

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
