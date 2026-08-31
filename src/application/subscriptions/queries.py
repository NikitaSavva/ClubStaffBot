from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListActiveSubscriptionPlansQuery:
    actor_telegram_id: int


@dataclass(frozen=True, slots=True)
class GetMySubscriptionQuery:
    actor_telegram_id: int
