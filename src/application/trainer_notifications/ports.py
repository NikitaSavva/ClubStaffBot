from datetime import datetime
from typing import Protocol

from application.trainer_notifications.dto import (
    TrainerNotificationClaim,
    TrainerNotificationMessage,
    TrainerNotificationSession,
)


class TrainerNotificationReader(Protocol):
    async def find_due_session_ids(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[int, ...]: ...

    async def get_session(
        self,
        training_session_id: int,
    ) -> TrainerNotificationSession | None: ...

    async def count_expected(
        self,
        *,
        training_group_id: int,
        group_is_regular: bool,
        reference_now: datetime,
    ) -> int: ...

    async def count_confirmed(self, training_session_id: int) -> int: ...


class TrainerNotificationDeliveryRepository(Protocol):
    async def claim(
        self,
        *,
        training_session_id: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
        delivery_attempt: int,
        notification_id: int | None,
        stale_pending_before: datetime,
        max_attempts: int,
        reference_now: datetime,
    ) -> TrainerNotificationClaim: ...

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


class TrainerNotifier(Protocol):
    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None: ...
