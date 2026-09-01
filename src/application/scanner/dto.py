from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class TrustedTelegramWebAppUser:
    telegram_user_id: int


@dataclass(frozen=True, slots=True)
class ResolveAthleteQrResult:
    full_name: str
    birth_date: date | None
