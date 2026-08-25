from dishka import Provider, Scope, provide

from application.athletes import CreateManualAthleteInteractor
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


class ApplicationProvider(Provider):
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
    ) -> GetUserMenuContextInteractor:
        return GetUserMenuContextInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
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
