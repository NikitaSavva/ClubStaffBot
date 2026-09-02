from datetime import datetime


class RetryableTrainerNotificationDeliveryError(Exception):
    def __init__(
        self,
        *,
        training_session_id: int,
        starts_at: datetime,
        retry_after_seconds: int | None,
    ) -> None:
        super().__init__("Trainer notification delivery can be retried")
        self.training_session_id = training_session_id
        self.starts_at = starts_at
        self.retry_after_seconds = retry_after_seconds


class RetryableTrainerNotifierError(Exception):
    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        super().__init__("Trainer notifier is temporarily unavailable")
        self.retry_after_seconds = retry_after_seconds


class PermanentTrainerNotifierError(Exception):
    pass
