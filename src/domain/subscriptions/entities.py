from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from domain.club import TrainingGroupType


class SubscriptionAccessScope(StrEnum):
    SPECIFIC_GROUP = "SPECIFIC_GROUP"
    ALL_REGULAR_GROUPS = "ALL_REGULAR_GROUPS"


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    id: int
    code: str
    name: str
    visit_limit: int | None
    duration_months: int
    price: Decimal
    is_unlimited: bool
    access_scope: SubscriptionAccessScope
    required_group_type: TrainingGroupType | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class Subscription:
    id: int | None
    athlete_id: int
    group_id: int | None
    plan_id: int
    activated_by_user_id: int
    activated_at: datetime
    starts_at: datetime
    expires_at: datetime
    activation_price: Decimal
    remaining_visits: int | None
    status: SubscriptionStatus

    def is_effectively_active(self, reference_now: datetime) -> bool:
        return (
            self.status is SubscriptionStatus.ACTIVE
            and self.starts_at <= reference_now < self.expires_at
        )

    def is_elapsed_active(self, reference_now: datetime) -> bool:
        return (
            self.status is SubscriptionStatus.ACTIVE
            and self.expires_at <= reference_now
        )
