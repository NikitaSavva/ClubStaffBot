from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolveAthleteQrQuery:
    actor_telegram_id: int
    athlete_qr_token: str
