from datetime import date
from uuid import UUID

import pytest

from application.athlete_qr import AthleteQrTokenExpiredError
from application.attendance import (
    AttendanceAthleteDetails,
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
)
from application.scanner import (
    ConfirmAttendanceByQrCommand,
    ConfirmAttendanceByQrInteractor,
)

ACTOR_TELEGRAM_ID = 100_200
ATHLETE_PUBLIC_ID = UUID("12345678-1234-4678-9234-567812345678")


class FakeCodec:
    def __init__(self, error: Exception | None = None) -> None:
        self.tokens: list[str] = []
        self.error = error

    def verify(self, token: str) -> UUID:
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return ATHLETE_PUBLIC_ID


class FakeConfirmAttendance:
    def __init__(self) -> None:
        self.commands: list[object] = []

    async def __call__(self, command: object) -> ConfirmAttendanceResult:
        self.commands.append(command)
        return ConfirmAttendanceResult(
            outcome=ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION,
            athlete=AttendanceAthleteDetails(
                full_name="Иван Иванов",
                birth_date=date(1991, 12, 27),
            ),
        )


async def test_qr_wrapper_verifies_token_and_forces_qr_source() -> None:
    codec = FakeCodec()
    confirm = FakeConfirmAttendance()
    interactor = ConfirmAttendanceByQrInteractor(
        token_codec=codec,
        confirm_attendance=confirm,  # type: ignore[arg-type]
    )

    result = await interactor(
        ConfirmAttendanceByQrCommand(
            actor_telegram_id=ACTOR_TELEGRAM_ID,
            athlete_qr_token="signed-token",
            training_session_id=77,
        )
    )

    assert result.outcome is ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION
    assert codec.tokens == ["signed-token"]
    command = confirm.commands[0]
    assert command.actor_telegram_id == ACTOR_TELEGRAM_ID  # type: ignore[attr-defined]
    assert command.athlete_public_id == ATHLETE_PUBLIC_ID  # type: ignore[attr-defined]
    assert command.source.value == "QR"  # type: ignore[attr-defined]
    assert command.training_session_id == 77  # type: ignore[attr-defined]


async def test_expired_qr_between_selection_and_confirm_never_calls_core() -> None:
    codec = FakeCodec(AthleteQrTokenExpiredError())
    confirm = FakeConfirmAttendance()
    interactor = ConfirmAttendanceByQrInteractor(
        token_codec=codec,
        confirm_attendance=confirm,  # type: ignore[arg-type]
    )

    with pytest.raises(AthleteQrTokenExpiredError):
        await interactor(
            ConfirmAttendanceByQrCommand(
                actor_telegram_id=ACTOR_TELEGRAM_ID,
                athlete_qr_token="now-expired-token",
                training_session_id=77,
            )
        )

    assert codec.tokens == ["now-expired-token"]
    assert confirm.commands == []
