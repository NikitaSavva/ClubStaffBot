from datetime import datetime
from typing import Protocol

from application.notification_delivery import NotificationDeliveryRepository
from application.trainer_notifications.dto import (
    TrainerNotificationMessage,
    TrainerNotificationSession,
)

TrainerNotificationDeliveryRepository = NotificationDeliveryRepository


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


class TrainerNotifier(Protocol):
    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None: ...
