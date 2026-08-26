from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActivateSubscriptionCommand:
    actor_telegram_id: int
    athlete_id: int
    subscription_plan_id: int
    training_group_id: int | None
