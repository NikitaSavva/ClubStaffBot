from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListAthletesQuery:
    actor_telegram_id: int
