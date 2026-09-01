from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from domain.club import TrainingGroupType, TrainingSessionStatus


class ConfirmAttendanceOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    SESSION_SELECTION_REQUIRED = "SESSION_SELECTION_REQUIRED"
    NO_ACTIVE_SUBSCRIPTION = "NO_ACTIVE_SUBSCRIPTION"
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
    VISITS_EXHAUSTED = "VISITS_EXHAUSTED"
    NO_TRAINING_SESSION = "NO_TRAINING_SESSION"
    TRAINING_SESSION_CANCELLED = "TRAINING_SESSION_CANCELLED"
    ATTENDANCE_ALREADY_EXISTS = "ATTENDANCE_ALREADY_EXISTS"
    TRAINING_SESSION_NOT_ALLOWED = "TRAINING_SESSION_NOT_ALLOWED"
    TRAINING_SESSION_AMBIGUOUS = "TRAINING_SESSION_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class AttendanceAthleteDetails:
    full_name: str
    birth_date: date | None


@dataclass(frozen=True, slots=True)
class AttendanceSessionCandidate:
    id: int
    training_group_id: int
    starts_at: datetime
    ends_at: datetime
    status: TrainingSessionStatus
    group_type: TrainingGroupType
    sport_direction_name: str
    group_name: str


@dataclass(frozen=True, slots=True)
class ConfirmedAttendanceSession:
    starts_at: datetime
    sport_direction_name: str
    group_name: str


@dataclass(frozen=True, slots=True)
class SelectableAttendanceSession:
    training_session_id: int
    starts_at: datetime
    status: TrainingSessionStatus
    sport_direction_name: str
    group_name: str
    selectable: bool


@dataclass(frozen=True, slots=True)
class ConfirmAttendanceResult:
    outcome: ConfirmAttendanceOutcome
    athlete: AttendanceAthleteDetails
    session: ConfirmedAttendanceSession | None = None
    sessions: tuple[SelectableAttendanceSession, ...] = ()
    remaining_visits: int | None = None
    subscription_finished: bool = False
