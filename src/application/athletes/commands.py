from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CreateManualAthleteCommand:
    actor_telegram_id: int
    first_name: str
    last_name: str
    birth_date: date | None
