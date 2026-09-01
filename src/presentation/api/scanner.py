from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

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
    ResolveAthleteQrInteractor,
    ResolveAthleteQrQuery,
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
    TelegramWebAppInitDataVerifier,
)
from presentation.api.schemas import (
    ApiErrorResponse,
    ScannerResolveRequest,
    ScannerResolveResponse,
)

router = APIRouter(prefix="/api/webapp/scanner", tags=["webapp-scanner"])


@router.post(
    "/resolve",
    response_model=ScannerResolveResponse,
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
    },
)
@inject
async def resolve_athlete_qr(
    request: ScannerResolveRequest,
    verifier: FromDishka[TelegramWebAppInitDataVerifier],
    interactor: FromDishka[ResolveAthleteQrInteractor],
    telegram_init_data: Annotated[
        str | None,
        Header(alias="X-Telegram-Init-Data"),
    ] = None,
) -> ScannerResolveResponse | JSONResponse:
    return await resolve_athlete_qr_request(
        request=request,
        telegram_init_data=telegram_init_data,
        verifier=verifier,
        interactor=interactor,
    )


async def resolve_athlete_qr_request(
    *,
    request: ScannerResolveRequest,
    telegram_init_data: str | None,
    verifier: TelegramWebAppInitDataVerifier,
    interactor: ResolveAthleteQrInteractor,
) -> ScannerResolveResponse | JSONResponse:
    try:
        trusted_user = verifier.verify(telegram_init_data or "")
        result = await interactor(
            ResolveAthleteQrQuery(
                actor_telegram_id=trusted_user.telegram_user_id,
                athlete_qr_token=request.token,
            )
        )
    except TelegramWebAppInitDataExpiredError:
        return _error_response(
            status_code=401,
            code="telegram_init_data_expired",
            message="Сессия Telegram устарела.",
        )
    except TelegramWebAppInitDataInvalidError:
        return _error_response(
            status_code=401,
            code="telegram_init_data_invalid",
            message="Не удалось подтвердить сессию Telegram.",
        )
    except (UserNotFoundError, AdministratorPermissionRequiredError):
        return _error_response(
            status_code=403,
            code="scanner_forbidden",
            message="У вас нет доступа к сканеру.",
        )
    except AthleteQrTokenExpiredError:
        return _error_response(
            status_code=422,
            code="athlete_qr_expired",
            message="QR-код спортсмена истёк.",
        )
    except (
        AthleteQrTokenInvalidSignatureError,
        AthleteQrTokenMalformedPayloadError,
    ):
        return _error_response(
            status_code=422,
            code="athlete_qr_invalid",
            message="Не удалось распознать QR спортсмена.",
        )
    except AthleteNotFoundError:
        return _error_response(
            status_code=404,
            code="athlete_not_found",
            message="Спортсмен не найден.",
        )

    return ScannerResolveResponse(
        full_name=result.full_name,
        birth_date=result.birth_date,
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    error = ApiErrorResponse(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )
