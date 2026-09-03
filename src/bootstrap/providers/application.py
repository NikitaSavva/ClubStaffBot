from zoneinfo import ZoneInfo

from dishka import Provider, Scope, provide

from application.athlete_notifications import (
    AthleteNotificationReader,
    AthleteNotifier,
    FindAthletesForSessionReminderInteractor,
    NotifyAthleteBeforeSessionInteractor,
)
from application.athlete_qr import (
    AthleteQrTokenCodec,
    GetAthleteQrTokenInteractor,
)
from application.athletes import (
    AthleteSelectionReader,
    CreateManualAthleteInteractor,
    GetAthleteSelectionInteractor,
    ListAthleteSelectionInteractor,
)
from application.attendance import (
    AttendanceRepository,
    AttendanceSessionRepository,
    ConfirmAttendanceInteractor,
)
from application.club import (
    AssignTrainingGroupTrainerInteractor,
    ListTrainerCandidatesInteractor,
    ListTrainingGroupsInteractor,
    TrainingGroupReader,
    TrainingGroupRepository,
)
from application.common import Clock, UnitOfWork
from application.identity.account_link import (
    CreateAthleteAccountLinkInviteInteractor,
    LinkAthleteAccountInteractor,
    ListUnlinkedAthletesInteractor,
)
from application.identity.interactors import (
    GetUserMenuContextInteractor,
    RegisterBotUserInteractor,
)
from application.identity.owner_assignment import AssignOwnerInteractor
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
from application.identity.role_management import (
    AssignUserRoleInteractor,
    RemoveUserRoleInteractor,
    SearchBotUsersInteractor,
)
from application.notification_delivery import NotificationDeliveryRepository
from application.scanner import ConfirmAttendanceByQrInteractor
from application.subscriptions import (
    ActivateSubscriptionInteractor,
    CorrectSubscriptionInteractor,
    GetLatestAthleteSubscriptionInteractor,
    GetMySubscriptionInteractor,
    LatestAthleteSubscriptionReader,
    ListActiveSubscriptionPlansInteractor,
    MySubscriptionReader,
    SubscriptionPlanReader,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from application.trainer_notifications import (
    FindSessionsForTrainerNotificationInteractor,
    NotifyTrainerBeforeSessionInteractor,
    TrainerNotificationDeliveryRepository,
    TrainerNotificationReader,
    TrainerNotifier,
)
from application.training_sessions import (
    CurrentWeekScheduleReader,
    GenerateTrainingSessionsInteractor,
    GetCurrentWeekScheduleInteractor,
    ScheduleRuleRepository,
    TrainingSessionGenerationWindowResolver,
    TrainingSessionRepository,
)
from bootstrap.config import Settings


class ApplicationProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_find_athlete_notification_candidates_interactor(
        self,
        reader: AthleteNotificationReader,
        clock: Clock,
    ) -> FindAthletesForSessionReminderInteractor:
        return FindAthletesForSessionReminderInteractor(
            reader=reader,
            clock=clock,
        )

    @provide(scope=Scope.REQUEST)
    def provide_notify_athlete_before_session_interactor(
        self,
        reader: AthleteNotificationReader,
        delivery_repository: NotificationDeliveryRepository,
        notifier: AthleteNotifier,
        unit_of_work: UnitOfWork,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> NotifyAthleteBeforeSessionInteractor:
        return NotifyAthleteBeforeSessionInteractor(
            reader=reader,
            delivery_repository=delivery_repository,
            notifier=notifier,
            unit_of_work=unit_of_work,
            clock=clock,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_find_trainer_notification_sessions_interactor(
        self,
        reader: TrainerNotificationReader,
        clock: Clock,
    ) -> FindSessionsForTrainerNotificationInteractor:
        return FindSessionsForTrainerNotificationInteractor(
            reader=reader,
            clock=clock,
        )

    @provide(scope=Scope.REQUEST)
    def provide_notify_trainer_before_session_interactor(
        self,
        reader: TrainerNotificationReader,
        delivery_repository: TrainerNotificationDeliveryRepository,
        notifier: TrainerNotifier,
        unit_of_work: UnitOfWork,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> NotifyTrainerBeforeSessionInteractor:
        return NotifyTrainerBeforeSessionInteractor(
            reader=reader,
            delivery_repository=delivery_repository,
            notifier=notifier,
            unit_of_work=unit_of_work,
            clock=clock,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_confirm_attendance_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        subscription_repository: SubscriptionRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        training_session_repository: AttendanceSessionRepository,
        attendance_repository: AttendanceRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> ConfirmAttendanceInteractor:
        return ConfirmAttendanceInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            subscription_repository=subscription_repository,
            subscription_plan_repository=subscription_plan_repository,
            training_session_repository=training_session_repository,
            attendance_repository=attendance_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_confirm_attendance_by_qr_interactor(
        self,
        token_codec: AthleteQrTokenCodec,
        confirm_attendance: ConfirmAttendanceInteractor,
    ) -> ConfirmAttendanceByQrInteractor:
        return ConfirmAttendanceByQrInteractor(
            token_codec=token_codec,
            confirm_attendance=confirm_attendance,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_athlete_qr_token_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        token_codec: AthleteQrTokenCodec,
    ) -> GetAthleteQrTokenInteractor:
        return GetAthleteQrTokenInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            token_codec=token_codec,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_current_week_schedule_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        subscription_reader: MySubscriptionReader,
        schedule_reader: CurrentWeekScheduleReader,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> GetCurrentWeekScheduleInteractor:
        return GetCurrentWeekScheduleInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            subscription_reader=subscription_reader,
            schedule_reader=schedule_reader,
            clock=clock,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_my_subscription_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reader: MySubscriptionReader,
        clock: Clock,
    ) -> GetMySubscriptionInteractor:
        return GetMySubscriptionInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            reader=reader,
            clock=clock,
        )

    @provide(scope=Scope.REQUEST)
    def provide_list_athlete_selection_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        athlete_reader: AthleteSelectionReader,
    ) -> ListAthleteSelectionInteractor:
        return ListAthleteSelectionInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            athlete_reader=athlete_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_athlete_selection_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        athlete_reader: AthleteSelectionReader,
    ) -> GetAthleteSelectionInteractor:
        return GetAthleteSelectionInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            athlete_reader=athlete_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_list_active_subscription_plans_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        subscription_plan_reader: SubscriptionPlanReader,
    ) -> ListActiveSubscriptionPlansInteractor:
        return ListActiveSubscriptionPlansInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            subscription_plan_reader=subscription_plan_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_activate_subscription_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        training_group_repository: TrainingGroupRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        subscription_repository: SubscriptionRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> ActivateSubscriptionInteractor:
        return ActivateSubscriptionInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            training_group_repository=training_group_repository,
            subscription_plan_repository=subscription_plan_repository,
            subscription_repository=subscription_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
        )

    @provide(scope=Scope.APP)
    def provide_training_session_generation_window_resolver(
        self,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> TrainingSessionGenerationWindowResolver:
        return TrainingSessionGenerationWindowResolver(
            clock=clock,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_generate_training_sessions_interactor(
        self,
        schedule_rule_repository: ScheduleRuleRepository,
        training_session_repository: TrainingSessionRepository,
        unit_of_work: UnitOfWork,
        club_timezone: ZoneInfo,
    ) -> GenerateTrainingSessionsInteractor:
        return GenerateTrainingSessionsInteractor(
            schedule_rule_repository=schedule_rule_repository,
            training_session_repository=training_session_repository,
            unit_of_work=unit_of_work,
            club_timezone=club_timezone,
        )

    @provide(scope=Scope.REQUEST)
    def provide_list_training_groups_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        training_group_reader: TrainingGroupReader,
    ) -> ListTrainingGroupsInteractor:
        return ListTrainingGroupsInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            training_group_reader=training_group_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_list_trainer_candidates_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        bot_user_reader: BotUserReader,
    ) -> ListTrainerCandidatesInteractor:
        return ListTrainerCandidatesInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            bot_user_reader=bot_user_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_assign_training_group_trainer_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        training_group_repository: TrainingGroupRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> AssignTrainingGroupTrainerInteractor:
        return AssignTrainingGroupTrainerInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            training_group_repository=training_group_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
        )

    @provide(scope=Scope.REQUEST)
    def provide_assign_owner_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> AssignOwnerInteractor:
        return AssignOwnerInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
        )

    @provide(scope=Scope.REQUEST)
    def provide_search_bot_users_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        bot_user_reader: BotUserReader,
    ) -> SearchBotUsersInteractor:
        return SearchBotUsersInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            bot_user_reader=bot_user_reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_assign_user_role_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> AssignUserRoleInteractor:
        return AssignUserRoleInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
        )

    @provide(scope=Scope.REQUEST)
    def provide_remove_user_role_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> RemoveUserRoleInteractor:
        return RemoveUserRoleInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
        )

    @provide(scope=Scope.REQUEST)
    def provide_create_manual_athlete_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> CreateManualAthleteInteractor:
        return CreateManualAthleteInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
        )

    @provide(scope=Scope.REQUEST)
    def provide_list_unlinked_athletes_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
    ) -> ListUnlinkedAthletesInteractor:
        return ListUnlinkedAthletesInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
        )

    @provide(scope=Scope.REQUEST)
    def provide_create_athlete_account_link_invite_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        token_generator: InviteTokenGenerator,
        token_hasher: InviteTokenHasher,
    ) -> CreateAthleteAccountLinkInviteInteractor:
        return CreateAthleteAccountLinkInviteInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            bot_invite_repository=bot_invite_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            token_generator=token_generator,
            token_hasher=token_hasher,
        )

    @provide(scope=Scope.REQUEST)
    def provide_link_athlete_account_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        token_hasher: InviteTokenHasher,
    ) -> LinkAthleteAccountInteractor:
        return LinkAthleteAccountInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            bot_invite_repository=bot_invite_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
            token_hasher=token_hasher,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_user_menu_context_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        settings: Settings,
    ) -> GetUserMenuContextInteractor:
        return GetUserMenuContextInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            scanner_webapp_url=settings.telegram_scanner_webapp_url,
        )

    @provide(scope=Scope.REQUEST)
    def provide_register_bot_user_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        token_hasher: InviteTokenHasher,
        link_athlete_account_interactor: LinkAthleteAccountInteractor,
    ) -> RegisterBotUserInteractor:
        return RegisterBotUserInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            bot_invite_repository=bot_invite_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
            token_hasher=token_hasher,
            link_athlete_account_interactor=link_athlete_account_interactor,
        )

    @provide(scope=Scope.REQUEST)
    def provide_get_latest_athlete_subscription_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reader: LatestAthleteSubscriptionReader,
    ) -> GetLatestAthleteSubscriptionInteractor:
        return GetLatestAthleteSubscriptionInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            reader=reader,
        )

    @provide(scope=Scope.REQUEST)
    def provide_correct_subscription_interactor(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        subscription_repository: SubscriptionRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> CorrectSubscriptionInteractor:
        return CorrectSubscriptionInteractor(
            user_repository=user_repository,
            athlete_repository=athlete_repository,
            role_repository=role_repository,
            subscription_plan_repository=subscription_plan_repository,
            subscription_repository=subscription_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
        )
