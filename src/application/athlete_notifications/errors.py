from datetime import datetime


class RetryableAthleteNotificationDeliveryError(Exception):
    def __init__(
        self,
        *,
        training_session_id: int,
        athlete_id: int,
        notification_id: int,
        delivery_attempt: int,
        reminder_window_ends_at: datetime,
        retry_after_seconds: int | None,
    ) -> None:
        super().__init__("Athlete notification delivery can be retried")
        self.training_session_id = training_session_id
        self.athlete_id = athlete_id
        self.notification_id = notification_id
        self.delivery_attempt = delivery_attempt
        self.reminder_window_ends_at = reminder_window_ends_at
        self.retry_after_seconds = retry_after_seconds
