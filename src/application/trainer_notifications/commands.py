from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotifyTrainerBeforeSessionCommand:
    training_session_id: int
    delivery_attempt: int = 1
    notification_id: int | None = None

    def __post_init__(self) -> None:
        if self.delivery_attempt < 1:
            raise ValueError("delivery_attempt must be positive")
        if self.delivery_attempt > 1 and self.notification_id is None:
            raise ValueError("notification_id is required for retry delivery")
