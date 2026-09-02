from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.club import TrainingGroupType, TrainingSessionStatus


class TrainerNotificationClaimOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    ALREADY_SENT = "ALREADY_SENT"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    IN_PROGRESS = "IN_PROGRESS"


class NotifyTrainerOutcome(StrEnum):
    SENT = "SENT"
    ALREADY_SENT = "ALREADY_SENT"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    NOT_DUE = "NOT_DUE"
    CANCELLED = "CANCELLED"
    SESSION_STARTED = "SESSION_STARTED"
    TRAINER_UNAVAILABLE = "TRAINER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FindTrainerNotificationSessionsResult:
    reference_now: datetime
    training_session_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TrainerNotificationSession:
    id: int
    group_id: int
    trainer_id: int
    starts_at: datetime
    ends_at: datetime
    status: TrainingSessionStatus
    group_type: TrainingGroupType
    sport_direction_name: str
    group_name: str
    trainer_user_exists: bool
    trainer_telegram_id: int | None


@dataclass(frozen=True, slots=True)
class TrainerNotificationClaim:
    outcome: TrainerNotificationClaimOutcome
    attempts: int


@dataclass(frozen=True, slots=True)
class TrainerNotificationMessage:
    sport_direction_name: str
    group_name: str
    starts_at: datetime
    ends_at: datetime
    expected_count: int
    confirmed_count: int


@dataclass(frozen=True, slots=True)
class NotifyTrainerBeforeSessionResult:
    outcome: NotifyTrainerOutcome
    training_session_id: int
    attempts: int = 0
