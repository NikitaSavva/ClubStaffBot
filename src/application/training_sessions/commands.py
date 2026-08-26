from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class GenerateTrainingSessionsCommand:
    date_from: date
    date_to: date
