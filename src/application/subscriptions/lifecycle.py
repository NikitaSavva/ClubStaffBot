from datetime import datetime

from application.subscriptions.ports import SubscriptionRepository
from domain.subscriptions import Subscription


def resolve_effective_active_subscription(
    subscription: Subscription | None,
    reference_now: datetime,
) -> Subscription | None:
    if subscription is None or not subscription.is_effectively_active(
        reference_now
    ):
        return None
    return subscription


async def expire_if_elapsed(
    subscription: Subscription,
    *,
    reference_now: datetime,
    repository: SubscriptionRepository,
) -> bool:
    if not subscription.is_elapsed_active(reference_now):
        return False
    if subscription.id is None:
        raise RuntimeError("A persisted Subscription must have an id")
    expired = await repository.mark_expired(subscription.id)
    if not expired:
        raise RuntimeError("The locked ACTIVE Subscription was not expired")
    return True
