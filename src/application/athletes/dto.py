from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateManualAthleteResult:
    first_name: str
