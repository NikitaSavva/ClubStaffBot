from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GetUserMenuContextQuery:
    telegram_id: int
