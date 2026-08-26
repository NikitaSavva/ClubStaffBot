from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CreateManualAthleteResult:
    first_name: str
    last_name: str
    birth_date: date


@dataclass(frozen=True, slots=True)
class AthleteSummary:
    athlete_id: int
    first_name: str
    last_name: str | None
    birth_date: date | None

    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
        )
