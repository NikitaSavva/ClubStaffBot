from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from domain.club import TrainingGroupType
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)


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


@dataclass(frozen=True, slots=True)
class MySubscriptionGroup:
    training_group_id: int
    direction_name: str
    group_name: str


@dataclass(frozen=True, slots=True)
class PersistedActiveSubscriptionReadModel:
    subscription: Subscription
    plan_name: str
    is_unlimited: bool
    access_scope: SubscriptionAccessScope
    group: MySubscriptionGroup | None


@dataclass(frozen=True, slots=True)
class AthleteSubscriptionReadModel:
    athlete_id: int
    persisted_active: PersistedActiveSubscriptionReadModel | None


@dataclass(frozen=True, slots=True)
class MySubscriptionDetails:
    plan_name: str
    is_unlimited: bool
    access_scope: SubscriptionAccessScope
    group: MySubscriptionGroup | None
    starts_at: datetime
    expires_at: datetime
    remaining_visits: int | None


@dataclass(frozen=True, slots=True)
class GetMySubscriptionResult:
    current: MySubscriptionDetails | None


@dataclass(frozen=True, slots=True)
class LatestSubscriptionDetails:
    subscription_id: int
    plan_name: str
    is_unlimited: bool
    access_scope: SubscriptionAccessScope
    group: MySubscriptionGroup | None
    starts_at: datetime
    expires_at: datetime
    remaining_visits: int | None
    status: SubscriptionStatus


@dataclass(frozen=True, slots=True)
class AthleteLatestSubscriptionReadModel:
    athlete_id: int
    athlete_full_name: str
    latest: LatestSubscriptionDetails | None


@dataclass(frozen=True, slots=True)
class GetLatestAthleteSubscriptionResult:
    athlete_id: int
    athlete_full_name: str
    latest: LatestSubscriptionDetails | None


class CorrectSubscriptionOutcome(StrEnum):
    CORRECTED = "CORRECTED"
    NO_CHANGES = "NO_CHANGES"


@dataclass(frozen=True, slots=True)
class CorrectSubscriptionResult:
    outcome: CorrectSubscriptionOutcome
    athlete_id: int
    subscription_id: int
