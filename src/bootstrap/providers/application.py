from dishka import Provider, Scope, provide

from application.common import Clock, UnitOfWork
from application.identity.interactors import RegisterBotUserInteractor
from application.identity.ports import (
    AuditLogRepository,
    BotInviteRepository,
    InviteTokenHasher,
    RoleRepository,
    UserRepository,
)


class ApplicationProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_register_bot_user_interactor(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        token_hasher: InviteTokenHasher,
    ) -> RegisterBotUserInteractor:
        return RegisterBotUserInteractor(
            user_repository=user_repository,
            role_repository=role_repository,
            bot_invite_repository=bot_invite_repository,
            audit_log_repository=audit_log_repository,
            unit_of_work=unit_of_work,
            clock=clock,
            token_hasher=token_hasher,
        )
