from dataclasses import dataclass

from application.athletes.dto import AthleteSearch


@dataclass(frozen=True, slots=True)
class ListAthleteSelectionQuery:
    actor_telegram_id: int
    page: int = 0
    search: AthleteSearch | None = None


@dataclass(frozen=True, slots=True)
class GetAthleteSelectionQuery:
    actor_telegram_id: int
    athlete_id: int
