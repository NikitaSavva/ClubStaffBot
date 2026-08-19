from dishka import Provider, Scope, provide

from application.common import Clock
from application.identity.ports import InviteTokenHasher
from infrastructure.clock import SystemClock
from infrastructure.security import Sha256InviteTokenHasher


class InfrastructureProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_clock(self) -> Clock:
        return SystemClock()

    @provide(scope=Scope.APP)
    def provide_invite_token_hasher(self) -> InviteTokenHasher:
        return Sha256InviteTokenHasher()
