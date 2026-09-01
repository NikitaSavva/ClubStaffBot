from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfirmAttendanceByQrCommand:
    actor_telegram_id: int
    athlete_qr_token: str
    training_session_id: int | None = None
