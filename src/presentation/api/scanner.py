from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from application.athlete_qr import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)
from application.attendance import (
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from application.scanner import (
    ConfirmAttendanceByQrCommand,
    ConfirmAttendanceByQrInteractor,
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
    TelegramWebAppInitDataVerifier,
)
from presentation.api.schemas import (
    ApiErrorResponse,
    ScannerAttendanceAthleteResponse,
    ScannerAttendanceRequest,
    ScannerAttendanceResponse,
    ScannerConfirmedSessionResponse,
    ScannerSelectableSessionResponse,
)

router = APIRouter(prefix="/api/webapp/scanner", tags=["webapp-scanner"])


@router.post(
    "/attendance",
    response_model=ScannerAttendanceResponse,
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
    },
)
@inject
async def confirm_attendance_by_qr(
    request: ScannerAttendanceRequest,
    verifier: FromDishka[TelegramWebAppInitDataVerifier],
    interactor: FromDishka[ConfirmAttendanceByQrInteractor],
    telegram_init_data: Annotated[
        str | None,
        Header(alias="X-Telegram-Init-Data"),
    ] = None,
) -> ScannerAttendanceResponse | JSONResponse:
    return await confirm_attendance_by_qr_request(
        request=request,
        telegram_init_data=telegram_init_data,
        verifier=verifier,
        interactor=interactor,
    )


async def confirm_attendance_by_qr_request(
    *,
    request: ScannerAttendanceRequest,
    telegram_init_data: str | None,
    verifier: TelegramWebAppInitDataVerifier,
    interactor: ConfirmAttendanceByQrInteractor,
) -> ScannerAttendanceResponse | JSONResponse:
    try:
        trusted_user = verifier.verify(telegram_init_data or "")
        result = await interactor(
            ConfirmAttendanceByQrCommand(
                actor_telegram_id=trusted_user.telegram_user_id,
                athlete_qr_token=request.token,
                training_session_id=request.training_session_id,
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

    return _result_response(result)


def _result_response(
    result: ConfirmAttendanceResult,
) -> ScannerAttendanceResponse | JSONResponse:
    athlete = ScannerAttendanceAthleteResponse(
        full_name=result.athlete.full_name,
        birth_date=result.athlete.birth_date,
    )
    session = (
        ScannerConfirmedSessionResponse(
            starts_at=result.session.starts_at,
            sport_direction_name=result.session.sport_direction_name,
            group_name=result.session.group_name,
        )
        if result.session is not None
        else None
    )
    if result.outcome is ConfirmAttendanceOutcome.CONFIRMED:
        return ScannerAttendanceResponse(
            state="confirmed",
            athlete=athlete,
            session=session,
            remaining_visits=result.remaining_visits,
            subscription_finished=result.subscription_finished,
        )
    if (
        result.outcome
        is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED
    ):
        return ScannerAttendanceResponse(
            state="session_selection_required",
            athlete=athlete,
            sessions=tuple(
                ScannerSelectableSessionResponse(
                    training_session_id=item.training_session_id,
                    starts_at=item.starts_at,
                    status=item.status.value,
                    sport_direction_name=item.sport_direction_name,
                    group_name=item.group_name,
                    selectable=item.selectable,
                )
                for item in result.sessions
            ),
        )

    code, message = _business_error(result.outcome)
    details: dict[str, object] = {
        "athlete": athlete.model_dump(mode="json"),
    }
    if session is not None:
        details["session"] = session.model_dump(mode="json")
    return _error_response(
        status_code=409,
        code=code,
        message=message,
        details=details,
    )


def _business_error(
    outcome: ConfirmAttendanceOutcome,
) -> tuple[str, str]:
    errors = {
        ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION: (
            "no_active_subscription",
            "У спортсмена нет активного абонемента.",
        ),
        ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED: (
            "subscription_expired",
            "Абонемент спортсмена истёк.",
        ),
        ConfirmAttendanceOutcome.VISITS_EXHAUSTED: (
            "visits_exhausted",
            "Посещения по абонементу закончились.",
        ),
        ConfirmAttendanceOutcome.NO_TRAINING_SESSION: (
            "no_training_session",
            "Сегодня для этой группы нет тренировки.",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED: (
            "training_session_cancelled",
            "Сегодняшняя тренировка отменена.",
        ),
        ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS: (
            "attendance_already_exists",
            "Посещение уже отмечено для этой тренировки.",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED: (
            "training_session_not_allowed",
            "Выбранная тренировка недоступна для отметки посещения.",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS: (
            "training_session_ambiguous",
            "Для группы найдено несколько тренировок на сегодня. "
            "Невозможно однозначно определить занятие.",
        ),
    }
    try:
        return errors[outcome]
    except KeyError as error:
        raise RuntimeError(f"Unexpected attendance outcome: {outcome}") from error


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    error = ApiErrorResponse(
        code=code,
        message=message,
        details=details or {},
    )
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )
