from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GetAthleteQrTokenQuery:
    actor_telegram_id: int
