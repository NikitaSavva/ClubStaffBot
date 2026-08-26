from typing import Protocol

from application.subscriptions.dto import SubscriptionPlanSummary
from domain.subscriptions import Subscription, SubscriptionPlan


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

    async def mark_expired(self, subscription_id: int) -> bool: ...

    async def add(self, subscription: Subscription) -> int: ...


class SubscriptionPlanReader(Protocol):
    async def list_active(self) -> tuple[SubscriptionPlanSummary, ...]: ...
