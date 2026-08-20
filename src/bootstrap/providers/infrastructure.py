from dishka import Provider, Scope, provide

from application.common import Clock
from application.identity.ports import InviteTokenGenerator, InviteTokenHasher
from infrastructure.clock import SystemClock
from infrastructure.security import (
    SecretsInviteTokenGenerator,
    Sha256InviteTokenHasher,
)


class InfrastructureProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_clock(self) -> Clock:
        return SystemClock()

    @provide(scope=Scope.APP)
    def provide_invite_token_hasher(self) -> InviteTokenHasher:
        return Sha256InviteTokenHasher()

    @provide(scope=Scope.APP)
    def provide_invite_token_generator(self) -> InviteTokenGenerator:
        return SecretsInviteTokenGenerator()
