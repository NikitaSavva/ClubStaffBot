from application.athlete_qr import AthleteQrTokenCodec
from application.attendance import (
    ConfirmAttendanceCommand,
    ConfirmAttendanceInteractor,
    ConfirmAttendanceResult,
)
from application.scanner.commands import ConfirmAttendanceByQrCommand
from domain.attendance import AttendanceSource


class ConfirmAttendanceByQrInteractor:
    def __init__(
        self,
        token_codec: AthleteQrTokenCodec,
        confirm_attendance: ConfirmAttendanceInteractor,
    ) -> None:
        self._token_codec = token_codec
        self._confirm_attendance = confirm_attendance

    async def __call__(
        self,
        command: ConfirmAttendanceByQrCommand,
    ) -> ConfirmAttendanceResult:
        athlete_public_id = self._token_codec.verify(
            command.athlete_qr_token
        )
        return await self._confirm_attendance(
            ConfirmAttendanceCommand(
                actor_telegram_id=command.actor_telegram_id,
                athlete_public_id=athlete_public_id,
                source=AttendanceSource.QR,
                training_session_id=command.training_session_id,
            )
        )
