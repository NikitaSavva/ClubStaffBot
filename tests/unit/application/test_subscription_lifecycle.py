from datetime import UTC, datetime, timedelta
from decimal import Decimal

from application.subscriptions.lifecycle import (
    resolve_effective_active_subscription,
)
from domain.subscriptions import Subscription, SubscriptionStatus

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def subscription(
    *,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    starts_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(seconds=1),
) -> Subscription:
    return Subscription(
        id=1,
        athlete_id=2,
        group_id=3,
        plan_id=4,
        activated_by_user_id=5,
        activated_at=NOW,
        starts_at=starts_at,
        expires_at=expires_at,
        activation_price=Decimal("4000"),
        remaining_visits=8,
        status=status,
    )


def test_resolver_returns_effective_active_subscription() -> None:
    current = subscription()

    assert resolve_effective_active_subscription(current, NOW) is current


def test_resolver_treats_elapsed_active_as_absent_without_mutation() -> None:
    current = subscription(expires_at=NOW)

    assert resolve_effective_active_subscription(current, NOW) is None
    assert current.status is SubscriptionStatus.ACTIVE


def test_resolver_rejects_expired_status_and_future_start() -> None:
    assert (
        resolve_effective_active_subscription(
            subscription(status=SubscriptionStatus.EXPIRED),
            NOW,
        )
        is None
    )
    assert (
        resolve_effective_active_subscription(
            subscription(starts_at=NOW + timedelta(seconds=1)),
            NOW,
        )
        is None
    )
