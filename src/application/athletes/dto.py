from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateManualAthleteResult:
    first_name: str
    last_name: str
    birth_date: date


class AthleteSearchKind(StrEnum):
    SURNAME = "SURNAME"
    TELEGRAM_USERNAME = "TELEGRAM_USERNAME"


@dataclass(frozen=True, slots=True)
class AthleteSearch:
    kind: AthleteSearchKind
    value: str


@dataclass(frozen=True, slots=True)
class AthleteSelectionItem:
    athlete_id: int
    athlete_public_id: UUID
    first_name: str
    last_name: str | None
    birth_date: date | None

    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
        )


@dataclass(frozen=True, slots=True)
class AthleteSelectionPage:
    items: tuple[AthleteSelectionItem, ...]
    page: int
    has_previous: bool
    has_next: bool
