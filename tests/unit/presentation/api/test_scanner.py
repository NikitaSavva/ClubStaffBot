import json
from datetime import date

import pytest
from pydantic import ValidationError

from application.athlete_qr import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from application.scanner import (
    ResolveAthleteQrQuery,
    ResolveAthleteQrResult,
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
    TrustedTelegramWebAppUser,
)
from presentation.api.scanner import resolve_athlete_qr_request
from presentation.api.schemas import (
    ScannerResolveRequest,
    ScannerResolveResponse,
)

TRUSTED_TELEGRAM_ID = 55_001
RAW_INIT_DATA = "query_id=signed-and-opaque"


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
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.queries: list[ResolveAthleteQrQuery] = []

    async def __call__(
        self,
        query: ResolveAthleteQrQuery,
    ) -> ResolveAthleteQrResult:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return ResolveAthleteQrResult(
            full_name="Иван Иванов",
            birth_date=date(1991, 12, 27),
        )


async def test_trusted_actor_comes_only_from_verified_init_data() -> None:
    verifier = FakeVerifier()
    interactor = FakeInteractor()

    response = await resolve_athlete_qr_request(
        request=ScannerResolveRequest(token="signed-athlete-token"),
        telegram_init_data=RAW_INIT_DATA,
        verifier=verifier,
        interactor=interactor,  # type: ignore[arg-type]
    )

    assert response == ScannerResolveResponse(
        full_name="Иван Иванов",
        birth_date=date(1991, 12, 27),
    )
    assert verifier.received == [RAW_INIT_DATA]
    assert interactor.queries == [
        ResolveAthleteQrQuery(
            actor_telegram_id=TRUSTED_TELEGRAM_ID,
            athlete_qr_token="signed-athlete-token",
        )
    ]


def test_request_schema_rejects_actor_identity_fields() -> None:
    with pytest.raises(ValidationError):
        ScannerResolveRequest.model_validate(
            {
                "token": "signed-athlete-token",
                "actor_telegram_id": 999,
            }
        )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            TelegramWebAppInitDataInvalidError(),
            401,
            "telegram_init_data_invalid",
        ),
        (
            TelegramWebAppInitDataExpiredError(),
            401,
            "telegram_init_data_expired",
        ),
        (UserNotFoundError(), 403, "scanner_forbidden"),
        (
            AdministratorPermissionRequiredError(),
            403,
            "scanner_forbidden",
        ),
        (AthleteNotFoundError(), 404, "athlete_not_found"),
        (
            AthleteQrTokenExpiredError(),
            422,
            "athlete_qr_expired",
        ),
        (
            AthleteQrTokenInvalidSignatureError(),
            422,
            "athlete_qr_invalid",
        ),
        (
            AthleteQrTokenMalformedPayloadError(),
            422,
            "athlete_qr_invalid",
        ),
    ],
)
async def test_controlled_errors_have_stable_api_codes(
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
    verifier = FakeVerifier(verifier_error)
    interactor = FakeInteractor(None if verifier_error else error)

    response = await resolve_athlete_qr_request(
        request=ScannerResolveRequest(token="opaque-token"),
        telegram_init_data=RAW_INIT_DATA,
        verifier=verifier,
        interactor=interactor,  # type: ignore[arg-type]
    )

    assert response.status_code == expected_status
    payload = json.loads(response.body)
    assert payload["code"] == expected_code
    assert payload["details"] == {}
    assert "traceback" not in payload
