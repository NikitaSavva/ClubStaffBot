from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GetUserMenuContextQuery:
    telegram_id: int


@dataclass(frozen=True, slots=True)
class ListUnlinkedAthletesQuery:
    actor_telegram_id: int
