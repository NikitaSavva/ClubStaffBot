from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AttendanceSource(StrEnum):
    QR = "QR"
    MANUAL = "MANUAL"


class AttendanceStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class Attendance:
    id: int | None
    training_session_id: int
    athlete_id: int
    subscription_id: int
    confirmed_by_user_id: int
    source: AttendanceSource
    status: AttendanceStatus
    confirmed_at: datetime
