from dataclasses import dataclass
from datetime import datetime

from domain.subscriptions import SubscriptionStatus


@dataclass(frozen=True, slots=True)
class ActivateSubscriptionCommand:
    actor_telegram_id: int
    athlete_id: int
    subscription_plan_id: int
    training_group_id: int | None


@dataclass(frozen=True, slots=True)
class CorrectSubscriptionCommand:
    actor_telegram_id: int
    athlete_id: int
    subscription_id: int
    remaining_visits_is_set: bool
    remaining_visits: int | None
    expires_at: datetime | None
    status: SubscriptionStatus | None
