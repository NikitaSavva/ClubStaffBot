from datetime import UTC, datetime, timedelta
from decimal import Decimal

from domain.subscriptions import Subscription, SubscriptionStatus

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def make_subscription(
    *,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    starts_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(days=1),
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


def test_subscription_is_effectively_active_inside_temporal_bounds() -> None:
    subscription = make_subscription()

    assert subscription.is_effectively_active(NOW)


def test_subscription_is_not_effectively_active_at_expiration_boundary() -> None:
    subscription = make_subscription(expires_at=NOW)

    assert not subscription.is_effectively_active(NOW)
    assert subscription.is_elapsed_active(NOW)


def test_expired_status_is_not_effectively_active() -> None:
    subscription = make_subscription(status=SubscriptionStatus.EXPIRED)

    assert not subscription.is_effectively_active(NOW)
    assert not subscription.is_elapsed_active(NOW)


def test_future_active_subscription_is_not_effectively_active() -> None:
    subscription = make_subscription(
        starts_at=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(days=1),
    )

    assert not subscription.is_effectively_active(NOW)
    assert not subscription.is_elapsed_active(NOW)
