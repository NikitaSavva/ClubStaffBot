from zoneinfo import ZoneInfo

from dishka import Provider, Scope, provide

from application.athlete_qr import AthleteQrTokenCodec
from application.common import Clock
from application.identity.ports import InviteTokenGenerator, InviteTokenHasher
from application.scanner import TelegramWebAppInitDataVerifier
from bootstrap.config import Settings
from infrastructure.athlete_qr import ItsDangerousAthleteQrTokenCodec
from infrastructure.clock import SystemClock
from infrastructure.security import (
    SecretsInviteTokenGenerator,
    Sha256InviteTokenHasher,
)
from infrastructure.telegram_webapp import (
    AiogramTelegramWebAppInitDataVerifier,
)


class InfrastructureProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_telegram_webapp_init_data_verifier(
        self,
        settings: Settings,
        clock: Clock,
    ) -> TelegramWebAppInitDataVerifier:
        return AiogramTelegramWebAppInitDataVerifier(
            bot_token=settings.telegram_bot_token.get_secret_value(),
            max_age_seconds=(
                settings.telegram_webapp_init_data_max_age_seconds
            ),
            clock=clock,
        )

    @provide(scope=Scope.APP)
    def provide_athlete_qr_token_codec(
        self,
        settings: Settings,
    ) -> AthleteQrTokenCodec:
        return ItsDangerousAthleteQrTokenCodec(
            secret=settings.athlete_qr_signing_secret.get_secret_value(),
            ttl_seconds=settings.athlete_qr_ttl_seconds,
        )

    @provide(scope=Scope.APP)
    def provide_clock(self) -> Clock:
        return SystemClock()

    @provide(scope=Scope.APP)
    def provide_club_timezone(self, settings: Settings) -> ZoneInfo:
        return ZoneInfo(settings.club_timezone)

    @provide(scope=Scope.APP)
    def provide_invite_token_hasher(self) -> InviteTokenHasher:
        return Sha256InviteTokenHasher()

    @provide(scope=Scope.APP)
    def provide_invite_token_generator(self) -> InviteTokenGenerator:
        return SecretsInviteTokenGenerator()
