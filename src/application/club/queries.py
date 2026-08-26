from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListTrainingGroupsQuery:
    actor_telegram_id: int


@dataclass(frozen=True, slots=True)
class ListTrainerCandidatesQuery:
    actor_telegram_id: int
