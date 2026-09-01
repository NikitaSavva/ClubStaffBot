import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from application.athlete_qr import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)
from application.attendance import (
    AttendanceAthleteDetails,
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
    ConfirmedAttendanceSession,
    SelectableAttendanceSession,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from application.scanner import (
    ConfirmAttendanceByQrCommand,
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
    TrustedTelegramWebAppUser,
)
from domain.club import TrainingSessionStatus
from presentation.api.scanner import confirm_attendance_by_qr_request
from presentation.api.schemas import (
    ScannerAttendanceRequest,
    ScannerAttendanceResponse,
)

TRUSTED_TELEGRAM_ID = 55_001
RAW_INIT_DATA = "query_id=signed-and-opaque"
STARTS_AT = datetime(2026, 9, 1, 19, tzinfo=UTC)


class FakeVerifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.received: list[str] = []

    def verify(self, raw_init_data: str) -> TrustedTelegramWebAppUser:
        self.received.append(raw_init_data)
        if self.error is not None:
            raise self.error
        return TrustedTelegramWebAppUser(
            telegram_user_id=TRUSTED_TELEGRAM_ID
        )


class FakeInteractor:
    def __init__(
        self,
        result: ConfirmAttendanceResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or confirmed_result()
        self.error = error
        self.commands: list[ConfirmAttendanceByQrCommand] = []

    async def __call__(
        self,
        command: ConfirmAttendanceByQrCommand,
    ) -> ConfirmAttendanceResult:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.result


def athlete() -> AttendanceAthleteDetails:
    return AttendanceAthleteDetails(
        full_name="Иван Иванов",
        birth_date=date(1991, 12, 27),
    )


def confirmed_result() -> ConfirmAttendanceResult:
    return ConfirmAttendanceResult(
        outcome=ConfirmAttendanceOutcome.CONFIRMED,
        athlete=athlete(),
        session=ConfirmedAttendanceSession(
            starts_at=STARTS_AT,
            sport_direction_name="Кикбоксинг",
            group_name="Взрослые",
        ),
        remaining_visits=7,
    )


async def test_trusted_actor_and_session_come_from_validated_contract() -> None:
    verifier = FakeVerifier()
    interactor = FakeInteractor()

    response = await confirm_attendance_by_qr_request(
        request=ScannerAttendanceRequest(
            token="signed-athlete-token",
            training_session_id=77,
        ),
        telegram_init_data=RAW_INIT_DATA,
        verifier=verifier,
        interactor=interactor,  # type: ignore[arg-type]
    )

    assert isinstance(response, ScannerAttendanceResponse)
    assert response.state == "confirmed"
    assert response.athlete.full_name == "Иван Иванов"
    assert response.remaining_visits == 7
    assert verifier.received == [RAW_INIT_DATA]
    assert interactor.commands == [
        ConfirmAttendanceByQrCommand(
            actor_telegram_id=TRUSTED_TELEGRAM_ID,
            athlete_qr_token="signed-athlete-token",
            training_session_id=77,
        )
    ]


@pytest.mark.parametrize("field", ["actor_telegram_id", "source"])
def test_request_schema_rejects_authority_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ScannerAttendanceRequest.model_validate(
            {
                "token": "signed-athlete-token",
                field: "MANUAL" if field == "source" else 999,
            }
        )


async def test_session_selection_contract_includes_cancelled_disabled() -> None:
    interactor = FakeInteractor(
        ConfirmAttendanceResult(
            outcome=ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED,
            athlete=athlete(),
            sessions=(
                SelectableAttendanceSession(
                    training_session_id=1,
                    starts_at=STARTS_AT,
                    status=TrainingSessionStatus.SCHEDULED,
                    sport_direction_name="MMA",
                    group_name="Взрослые",
                    selectable=True,
                ),
                SelectableAttendanceSession(
                    training_session_id=2,
                    starts_at=STARTS_AT,
                    status=TrainingSessionStatus.CANCELLED,
                    sport_direction_name="Кикбоксинг",
                    group_name="Девушки",
                    selectable=False,
                ),
            ),
        )
    )

    response = await confirm_attendance_by_qr_request(
        request=ScannerAttendanceRequest(token="token"),
        telegram_init_data=RAW_INIT_DATA,
        verifier=FakeVerifier(),
        interactor=interactor,  # type: ignore[arg-type]
    )

    assert isinstance(response, ScannerAttendanceResponse)
    assert response.state == "session_selection_required"
    assert [item.selectable for item in response.sessions] == [True, False]
    assert response.sessions[1].status == "CANCELLED"


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION, "no_active_subscription"),
        (ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED, "subscription_expired"),
        (ConfirmAttendanceOutcome.VISITS_EXHAUSTED, "visits_exhausted"),
        (ConfirmAttendanceOutcome.NO_TRAINING_SESSION, "no_training_session"),
        (
            ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED,
            "training_session_cancelled",
        ),
        (
            ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS,
            "attendance_already_exists",
        ),
        (
            ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED,
            "training_session_not_allowed",
        ),
        (
            ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS,
            "training_session_ambiguous",
        ),
    ],
)
async def test_business_outcomes_have_stable_codes(
    outcome: ConfirmAttendanceOutcome,
    expected_code: str,
) -> None:
    response = await confirm_attendance_by_qr_request(
        request=ScannerAttendanceRequest(token="token"),
        telegram_init_data=RAW_INIT_DATA,
        verifier=FakeVerifier(),
        interactor=FakeInteractor(
            ConfirmAttendanceResult(outcome=outcome, athlete=athlete())
        ),  # type: ignore[arg-type]
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["code"] == expected_code
    assert payload["details"]["athlete"]["full_name"] == "Иван Иванов"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (TelegramWebAppInitDataInvalidError(), 401, "telegram_init_data_invalid"),
        (TelegramWebAppInitDataExpiredError(), 401, "telegram_init_data_expired"),
        (UserNotFoundError(), 403, "scanner_forbidden"),
        (AdministratorPermissionRequiredError(), 403, "scanner_forbidden"),
        (AthleteNotFoundError(), 404, "athlete_not_found"),
        (AthleteQrTokenExpiredError(), 422, "athlete_qr_expired"),
        (AthleteQrTokenInvalidSignatureError(), 422, "athlete_qr_invalid"),
        (AthleteQrTokenMalformedPayloadError(), 422, "athlete_qr_invalid"),
    ],
)
async def test_security_errors_keep_stable_api_codes(
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    verifier_error = (
        error
        if isinstance(
            error,
            (
                TelegramWebAppInitDataInvalidError,
                TelegramWebAppInitDataExpiredError,
            ),
        )
        else None
    )
    response = await confirm_attendance_by_qr_request(
        request=ScannerAttendanceRequest(token="token"),
        telegram_init_data=RAW_INIT_DATA,
        verifier=FakeVerifier(verifier_error),
        interactor=FakeInteractor(error=None if verifier_error else error),  # type: ignore[arg-type]
    )

    assert response.status_code == expected_status
    payload = json.loads(response.body)
    assert payload["code"] == expected_code
    assert payload["details"] == {}
