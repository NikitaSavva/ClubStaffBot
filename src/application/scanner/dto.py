from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrustedTelegramWebAppUser:
    telegram_user_id: int
