import asyncio
from typing import Any

import structlog
from celery import shared_task  # type: ignore[import-untyped]
from dishka import AsyncContainer

from application.trainer_notifications import (
    FindSessionsForTrainerNotificationInteractor,
    FindTrainerNotificationSessionsResult,
    NotifyTrainerBeforeSessionCommand,
    NotifyTrainerBeforeSessionInteractor,
    NotifyTrainerBeforeSessionResult,
    NotifyTrainerOutcome,
    RetryableTrainerNotificationDeliveryError,
)
from bootstrap.config import Settings
from bootstrap.container import create_container

POLL_TRAINER_NOTIFICATIONS_TASK = "trainer_notifications.poll_due_sessions"
NOTIFY_TRAINER_BEFORE_SESSION_TASK = (
    "trainer_notifications.notify_before_session"
)
logger = structlog.get_logger()


async def find_with_container(
    container: AsyncContainer,
) -> FindTrainerNotificationSessionsResult:
    async with container() as request_container:
        interactor = await request_container.get(
            FindSessionsForTrainerNotificationInteractor
        )
        return await interactor()


async def notify_with_container(
    container: AsyncContainer,
    *,
    training_session_id: int,
    delivery_attempt: int,
    notification_id: int | None,
) -> NotifyTrainerBeforeSessionResult:
    async with container() as request_container:
        interactor = await request_container.get(
            NotifyTrainerBeforeSessionInteractor
        )
        return await interactor(
            NotifyTrainerBeforeSessionCommand(
                training_session_id=training_session_id,
                delivery_attempt=delivery_attempt,
                notification_id=notification_id,
            )
        )


async def run_find() -> FindTrainerNotificationSessionsResult:
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await find_with_container(container)
    finally:
        await container.close()


async def run_notify(
    *,
    training_session_id: int,
    delivery_attempt: int,
    notification_id: int | None,
) -> NotifyTrainerBeforeSessionResult:
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await notify_with_container(
            container,
            training_session_id=training_session_id,
            delivery_attempt=delivery_attempt,
            notification_id=notification_id,
        )
    finally:
        await container.close()


@shared_task(name=POLL_TRAINER_NOTIFICATIONS_TASK)  # type: ignore[untyped-decorator]
def poll_trainer_notifications() -> dict[str, int | str]:
    result = asyncio.run(run_find())
    for training_session_id in result.training_session_ids:
        notify_trainer_before_session.delay(
            training_session_id=training_session_id,
            delivery_attempt=1,
            notification_id=None,
        )
    logger.info(
        "trainer_notification_poll_completed",
        reference_now=result.reference_now.isoformat(),
        candidate_count=len(result.training_session_ids),
    )
    return {
        "reference_now": result.reference_now.isoformat(),
        "candidate_count": len(result.training_session_ids),
    }


@shared_task(
    bind=True,
    name=NOTIFY_TRAINER_BEFORE_SESSION_TASK,
    max_retries=3,
)  # type: ignore[untyped-decorator]
def notify_trainer_before_session(
    task: Any,
    *,
    training_session_id: int,
    delivery_attempt: int = 1,
    notification_id: int | None = None,
) -> dict[str, int | str]:
    logger.info(
        "trainer_notification_processing",
        training_session_id=training_session_id,
        delivery_attempt=delivery_attempt,
        notification_id=notification_id,
    )
    try:
        result = asyncio.run(
            run_notify(
                training_session_id=training_session_id,
                delivery_attempt=delivery_attempt,
                notification_id=notification_id,
            )
        )
    except RetryableTrainerNotificationDeliveryError as error:
        countdown = error.retry_after_seconds or (
            30 * (2 ** (error.delivery_attempt - 1))
        )
        logger.warning(
            "trainer_notification_retry_scheduled",
            training_session_id=training_session_id,
            delivery_attempt=error.delivery_attempt,
            next_delivery_attempt=error.delivery_attempt + 1,
            notification_id=error.notification_id,
            countdown_seconds=countdown,
        )
        raise task.retry(
            exc=error,
            countdown=countdown,
            args=(),
            kwargs={
                "training_session_id": training_session_id,
                "delivery_attempt": error.delivery_attempt + 1,
                "notification_id": error.notification_id,
            },
        ) from error

    log = (
        logger.info
        if result.outcome
        in {
            NotifyTrainerOutcome.SENT,
            NotifyTrainerOutcome.ALREADY_SENT,
            NotifyTrainerOutcome.IN_PROGRESS,
            NotifyTrainerOutcome.NOT_DUE,
            NotifyTrainerOutcome.CANCELLED,
            NotifyTrainerOutcome.SESSION_STARTED,
        }
        else logger.warning
    )
    log(
        "trainer_notification_processed",
        training_session_id=result.training_session_id,
        outcome=result.outcome.value,
        attempts=result.attempts,
    )
    return {
        "training_session_id": result.training_session_id,
        "outcome": result.outcome.value,
        "attempts": result.attempts,
    }
