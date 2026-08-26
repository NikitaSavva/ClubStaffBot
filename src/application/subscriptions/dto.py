from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from domain.club import TrainingGroupType
from domain.subscriptions import SubscriptionAccessScope


@dataclass(frozen=True, slots=True)
class SubscriptionPlanSummary:
    subscription_plan_id: int
    name: str
    price: Decimal
    duration_months: int
    visit_limit: int | None
    access_scope: SubscriptionAccessScope
    required_group_type: TrainingGroupType | None


@dataclass(frozen=True, slots=True)
class ActivateSubscriptionResult:
    subscription_id: int
    athlete_id: int
    athlete_full_name: str
    subscription_plan_id: int
    plan_name: str
    training_group_id: int | None
    starts_at: datetime
    expires_at: datetime
    remaining_visits: int | None
