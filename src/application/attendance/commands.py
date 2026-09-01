from dataclasses import dataclass
from uuid import UUID

from domain.attendance import AttendanceSource


@dataclass(frozen=True, slots=True)
class ConfirmAttendanceCommand:
    actor_telegram_id: int
    athlete_public_id: UUID
    source: AttendanceSource
    training_session_id: int | None = None
