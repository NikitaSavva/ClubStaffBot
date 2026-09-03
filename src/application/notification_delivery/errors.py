class RetryableNotificationSenderError(Exception):
    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        super().__init__("Notification sender is temporarily unavailable")
        self.retry_after_seconds = retry_after_seconds


class PermanentNotificationSenderError(Exception):
    pass
