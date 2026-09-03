from dataclasses import dataclass
from enum import StrEnum


class NotificationClaimOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    ALREADY_SENT = "ALREADY_SENT"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    outcome: NotificationClaimOutcome
    attempts: int
    notification_id: int | None
