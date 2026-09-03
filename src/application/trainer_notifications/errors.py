from datetime import datetime

from application.notification_delivery import (
    PermanentNotificationSenderError,
    RetryableNotificationSenderError,
)


class RetryableTrainerNotificationDeliveryError(Exception):
    def __init__(
        self,
        *,
        training_session_id: int,
        notification_id: int,
        delivery_attempt: int,
        starts_at: datetime,
        retry_after_seconds: int | None,
    ) -> None:
        super().__init__("Trainer notification delivery can be retried")
        self.training_session_id = training_session_id
        self.notification_id = notification_id
        self.delivery_attempt = delivery_attempt
        self.starts_at = starts_at
        self.retry_after_seconds = retry_after_seconds


RetryableTrainerNotifierError = RetryableNotificationSenderError
PermanentTrainerNotifierError = PermanentNotificationSenderError
