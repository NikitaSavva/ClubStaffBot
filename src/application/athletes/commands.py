from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateManualAthleteCommand:
    actor_telegram_id: int
    first_name: str
