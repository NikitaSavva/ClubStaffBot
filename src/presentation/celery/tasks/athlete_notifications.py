import asyncio
from typing import Any

import structlog
from celery import shared_task
from dishka import AsyncContainer

from application.athlete_notifications import (
    FindAthleteNotificationCandidatesResult,
    FindAthletesForSessionReminderInteractor,
    NotifyAthleteBeforeSessionCommand,
    NotifyAthleteBeforeSessionInteractor,
    NotifyAthleteBeforeSessionResult,
    NotifyAthleteOutcome,
    RetryableAthleteNotificationDeliveryError,
    default_retry_delay_seconds,
)
from bootstrap.config import Settings
from bootstrap.container import create_container

POLL_ATHLETE_NOTIFICATIONS_TASK = "athlete_notifications.poll_due_recipients"
NOTIFY_ATHLETE_BEFORE_SESSION_TASK = (
    "athlete_notifications.notify_before_session"
)
logger = structlog.get_logger()


async def find_with_container(
    container: AsyncContainer,
) -> FindAthleteNotificationCandidatesResult:
    async with container() as request_container:
        interactor = await request_container.get(
            FindAthletesForSessionReminderInteractor
        )
        return await interactor()


async def notify_with_container(
    container: AsyncContainer,
    *,
    training_session_id: int,
    athlete_id: int,
    delivery_attempt: int,
    notification_id: int | None,
) -> NotifyAthleteBeforeSessionResult:
    async with container() as request_container:
        interactor = await request_container.get(
            NotifyAthleteBeforeSessionInteractor
        )
        return await interactor(
            NotifyAthleteBeforeSessionCommand(
                training_session_id=training_session_id,
                athlete_id=athlete_id,
                delivery_attempt=delivery_attempt,
                notification_id=notification_id,
            )
        )


async def run_find() -> FindAthleteNotificationCandidatesResult:
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await find_with_container(container)
    finally:
        await container.close()


async def run_notify(
    *,
    training_session_id: int,
    athlete_id: int,
    delivery_attempt: int,
    notification_id: int | None,
) -> NotifyAthleteBeforeSessionResult:
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await notify_with_container(
            container,
            training_session_id=training_session_id,
            athlete_id=athlete_id,
            delivery_attempt=delivery_attempt,
            notification_id=notification_id,
        )
    finally:
        await container.close()


@shared_task(name=POLL_ATHLETE_NOTIFICATIONS_TASK)
def poll_athlete_notifications() -> dict[str, int | str]:
    result = asyncio.run(run_find())
    for candidate in result.candidates:
        notify_athlete_before_session.delay(
            training_session_id=candidate.training_session_id,
            athlete_id=candidate.athlete_id,
            delivery_attempt=1,
            notification_id=None,
        )
    logger.info(
        "athlete_notification_poll_completed",
        reference_now=result.reference_now.isoformat(),
        candidate_count=len(result.candidates),
    )
    return {
        "reference_now": result.reference_now.isoformat(),
        "candidate_count": len(result.candidates),
    }


@shared_task(
    bind=True,
    name=NOTIFY_ATHLETE_BEFORE_SESSION_TASK,
    max_retries=3,
)
def notify_athlete_before_session(
    task: Any,
    *,
    training_session_id: int,
    athlete_id: int,
    delivery_attempt: int = 1,
    notification_id: int | None = None,
) -> dict[str, int | str]:
    logger.info(
        "athlete_notification_processing",
        training_session_id=training_session_id,
        athlete_id=athlete_id,
        delivery_attempt=delivery_attempt,
        notification_id=notification_id,
    )
    try:
        result = asyncio.run(
            run_notify(
                training_session_id=training_session_id,
                athlete_id=athlete_id,
                delivery_attempt=delivery_attempt,
                notification_id=notification_id,
            )
        )
    except RetryableAthleteNotificationDeliveryError as error:
        countdown = error.retry_after_seconds or default_retry_delay_seconds(
            error.delivery_attempt
        )
        logger.warning(
            "athlete_notification_retry_scheduled",
            training_session_id=training_session_id,
            athlete_id=athlete_id,
            delivery_attempt=error.delivery_attempt,
            next_delivery_attempt=error.delivery_attempt + 1,
            notification_id=error.notification_id,
            countdown_seconds=countdown,
            reminder_window_ends_at=(
                error.reminder_window_ends_at.isoformat()
            ),
        )
        raise task.retry(
            exc=error,
            countdown=countdown,
            args=(),
            kwargs={
                "training_session_id": training_session_id,
                "athlete_id": athlete_id,
                "delivery_attempt": error.delivery_attempt + 1,
                "notification_id": error.notification_id,
            },
        ) from error

    log = (
        logger.info
        if result.outcome
        in {
            NotifyAthleteOutcome.SENT,
            NotifyAthleteOutcome.ALREADY_SENT,
            NotifyAthleteOutcome.IN_PROGRESS,
            NotifyAthleteOutcome.NOT_DUE,
            NotifyAthleteOutcome.WINDOW_EXPIRED,
            NotifyAthleteOutcome.CANCELLED,
            NotifyAthleteOutcome.SESSION_STARTED,
            NotifyAthleteOutcome.ATHLETE_INELIGIBLE,
        }
        else logger.warning
    )
    log(
        "athlete_notification_processed",
        training_session_id=result.training_session_id,
        athlete_id=result.athlete_id,
        outcome=result.outcome.value,
        attempts=result.attempts,
    )
    return {
        "training_session_id": result.training_session_id,
        "athlete_id": result.athlete_id,
        "outcome": result.outcome.value,
        "attempts": result.attempts,
    }
