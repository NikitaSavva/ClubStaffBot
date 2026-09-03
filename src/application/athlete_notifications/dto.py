from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.club import TrainingSessionStatus


class NotifyAthleteOutcome(StrEnum):
    SENT = "SENT"
    ALREADY_SENT = "ALREADY_SENT"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    NOT_DUE = "NOT_DUE"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    CANCELLED = "CANCELLED"
    SESSION_STARTED = "SESSION_STARTED"
    ATHLETE_INELIGIBLE = "ATHLETE_INELIGIBLE"
    TELEGRAM_UNAVAILABLE = "TELEGRAM_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AthleteNotificationCandidate:
    training_session_id: int
    athlete_id: int


@dataclass(frozen=True, slots=True)
class FindAthleteNotificationCandidatesResult:
    reference_now: datetime
    candidates: tuple[AthleteNotificationCandidate, ...]


@dataclass(frozen=True, slots=True)
class AthleteNotificationSession:
    id: int
    group_id: int
    starts_at: datetime
    ends_at: datetime
    status: TrainingSessionStatus
    sport_direction_name: str
    group_name: str


@dataclass(frozen=True, slots=True)
class AthleteNotificationRecipient:
    athlete_id: int
    user_id: int
    telegram_id: int | None


@dataclass(frozen=True, slots=True)
class AthleteNotificationMessage:
    sport_direction_name: str
    group_name: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class NotifyAthleteBeforeSessionResult:
    outcome: NotifyAthleteOutcome
    training_session_id: int
    athlete_id: int
    attempts: int = 0
    notification_id: int | None = None
