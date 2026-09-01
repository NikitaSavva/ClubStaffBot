from typing import Protocol

from application.scanner.dto import TrustedTelegramWebAppUser


class TelegramWebAppInitDataVerifier(Protocol):
    def verify(self, raw_init_data: str) -> TrustedTelegramWebAppUser: ...
