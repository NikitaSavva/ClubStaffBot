from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotifyTrainerBeforeSessionCommand:
    training_session_id: int
    delivery_attempt: int = 1

    def __post_init__(self) -> None:
        if self.delivery_attempt < 1:
            raise ValueError("delivery_attempt must be positive")
