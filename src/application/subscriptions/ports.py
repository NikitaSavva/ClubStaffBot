from datetime import datetime
from typing import Protocol

from application.subscriptions.dto import (
    AthleteLatestSubscriptionReadModel,
    AthleteSubscriptionReadModel,
    SubscriptionPlanSummary,
)
from domain.subscriptions import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


class SubscriptionPlanRepository(Protocol):
    async def get_by_id(
        self,
        subscription_plan_id: int,
    ) -> SubscriptionPlan | None: ...


class SubscriptionRepository(Protocol):
    async def get_active_by_athlete(
        self,
        athlete_id: int,
    ) -> Subscription | None: ...

    async def get_active_by_athlete_for_update(
        self,
        athlete_id: int,
    ) -> Subscription | None: ...

    async def get_by_id_for_update(
        self,
        subscription_id: int,
    ) -> Subscription | None: ...

    async def get_latest_id_by_athlete(self, athlete_id: int) -> int | None: ...

    async def get_other_active_by_athlete(
        self,
        *,
        athlete_id: int,
        excluded_subscription_id: int,
    ) -> Subscription | None: ...

    async def mark_expired(self, subscription_id: int) -> bool: ...

    async def update_attendance_state(
        self,
        *,
        subscription_id: int,
        expected_remaining_visits: int,
        remaining_visits: int,
        status: SubscriptionStatus,
    ) -> bool: ...

    async def add(self, subscription: Subscription) -> int: ...

    async def update_correction(
        self,
        *,
        subscription_id: int,
        remaining_visits: int | None,
        expires_at: datetime,
        status: SubscriptionStatus,
    ) -> bool: ...


class SubscriptionPlanReader(Protocol):
    async def list_active(self) -> tuple[SubscriptionPlanSummary, ...]: ...


class MySubscriptionReader(Protocol):
    async def get_by_user_id(
        self,
        user_id: int,
    ) -> AthleteSubscriptionReadModel | None: ...


class LatestAthleteSubscriptionReader(Protocol):
    async def get_by_athlete_id(
        self,
        athlete_id: int,
    ) -> AthleteLatestSubscriptionReadModel | None: ...
