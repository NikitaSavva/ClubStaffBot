from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CreateManualAthleteResult:
    first_name: str
    last_name: str
    birth_date: date
