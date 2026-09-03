from datetime import datetime
from typing import Protocol

from application.notification_delivery.dto import NotificationClaim


class NotificationDeliveryRepository(Protocol):
    async def claim(
        self,
        *,
        notification_type: str,
        training_session_id: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
        delivery_attempt: int,
        notification_id: int | None,
        stale_pending_before: datetime,
        max_attempts: int,
        reference_now: datetime,
    ) -> NotificationClaim: ...

    async def mark_sent(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        attempts: int,
        sent_at: datetime,
    ) -> bool: ...

    async def mark_failed(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        reference_now: datetime,
    ) -> bool: ...

    async def refresh_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        reference_now: datetime,
    ) -> bool: ...

    async def release_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
    ) -> bool: ...

    async def release_stale_pending(
        self,
        *,
        idempotency_key: str,
        stale_pending_before: datetime,
    ) -> bool: ...
