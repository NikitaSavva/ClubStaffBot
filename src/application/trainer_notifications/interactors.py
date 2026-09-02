from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from application.common import Clock, UnitOfWork
from application.trainer_notifications.commands import (
    NotifyTrainerBeforeSessionCommand,
)
from application.trainer_notifications.dto import (
    FindTrainerNotificationSessionsResult,
    NotifyTrainerBeforeSessionResult,
    NotifyTrainerOutcome,
    TrainerNotificationClaimOutcome,
    TrainerNotificationMessage,
    TrainerNotificationSession,
)
from application.trainer_notifications.errors import (
    PermanentTrainerNotifierError,
    RetryableTrainerNotificationDeliveryError,
    RetryableTrainerNotifierError,
)
from application.trainer_notifications.ports import (
    TrainerNotificationDeliveryRepository,
    TrainerNotificationReader,
    TrainerNotifier,
)
from domain.club import TrainingGroupType, TrainingSessionStatus

NOTIFICATION_TYPE = "TRAINER_SESSION_MINUS_5"
NOTIFY_BEFORE = timedelta(minutes=5)
STALE_PENDING_AFTER = timedelta(minutes=10)
MAX_DELIVERY_ATTEMPTS = 4


def trainer_notification_idempotency_key(training_session_id: int) -> str:
    return f"{NOTIFICATION_TYPE}:{training_session_id}"


class FindSessionsForTrainerNotificationInteractor:
    def __init__(
        self,
        reader: TrainerNotificationReader,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock

    async def __call__(self) -> FindTrainerNotificationSessionsResult:
        reference_now = self._clock.now()
        session_ids = await self._reader.find_due_session_ids(
            reference_now=reference_now,
            notify_before_seconds=int(NOTIFY_BEFORE.total_seconds()),
            stale_pending_before=reference_now - STALE_PENDING_AFTER,
        )
        return FindTrainerNotificationSessionsResult(
            reference_now=reference_now,
            training_session_ids=session_ids,
        )


class NotifyTrainerBeforeSessionInteractor:
    def __init__(
        self,
        reader: TrainerNotificationReader,
        delivery_repository: TrainerNotificationDeliveryRepository,
        notifier: TrainerNotifier,
        unit_of_work: UnitOfWork,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> None:
        self._reader = reader
        self._deliveries = delivery_repository
        self._notifier = notifier
        self._uow = unit_of_work
        self._clock = clock
        self._club_timezone = club_timezone

    async def __call__(
        self,
        command: NotifyTrainerBeforeSessionCommand,
    ) -> NotifyTrainerBeforeSessionResult:
        reference_now = self._clock.now()
        async with self._uow:
            session = await self._reader.get_session(
                command.training_session_id
            )
            if session is None:
                return self._result(
                    command,
                    NotifyTrainerOutcome.SESSION_NOT_FOUND,
                )

            key = trainer_notification_idempotency_key(session.id)
            if session.status is TrainingSessionStatus.CANCELLED:
                await self._terminalize_without_send(
                    session=session,
                    idempotency_key=key,
                    reference_now=reference_now,
                )
                return self._result(command, NotifyTrainerOutcome.CANCELLED)

            if reference_now >= session.starts_at:
                await self._terminalize_without_send(
                    session=session,
                    idempotency_key=key,
                    reference_now=reference_now,
                )
                return self._result(
                    command,
                    NotifyTrainerOutcome.SESSION_STARTED,
                )

            if session.starts_at > reference_now + NOTIFY_BEFORE:
                released = False
                if command.delivery_attempt > 1:
                    released = await self._deliveries.release_pending(
                        idempotency_key=key,
                        expected_attempts=command.delivery_attempt - 1,
                    )
                else:
                    released = await self._deliveries.release_stale_pending(
                        idempotency_key=key,
                        stale_pending_before=(
                            reference_now - STALE_PENDING_AFTER
                        ),
                    )
                if released:
                    await self._uow.commit()
                return self._result(command, NotifyTrainerOutcome.NOT_DUE)

            if not session.trainer_user_exists:
                return self._result(
                    command,
                    NotifyTrainerOutcome.TRAINER_UNAVAILABLE,
                )

            if session.trainer_telegram_id is None:
                await self._terminalize_without_send(
                    session=session,
                    idempotency_key=key,
                    reference_now=reference_now,
                )
                return self._result(
                    command,
                    NotifyTrainerOutcome.TRAINER_UNAVAILABLE,
                )

            claim = await self._deliveries.claim(
                training_session_id=session.id,
                recipient_user_id=session.trainer_id,
                scheduled_at=session.starts_at - NOTIFY_BEFORE,
                idempotency_key=key,
                delivery_attempt=command.delivery_attempt,
                stale_pending_before=reference_now - STALE_PENDING_AFTER,
                max_attempts=MAX_DELIVERY_ATTEMPTS,
                reference_now=reference_now,
            )
            claim_result = self._claim_result(command, claim.outcome)
            if claim_result is not None:
                return claim_result

            expected_count = await self._reader.count_expected(
                training_group_id=session.group_id,
                group_is_regular=(
                    session.group_type is TrainingGroupType.REGULAR
                ),
                reference_now=reference_now,
            )
            confirmed_count = await self._reader.count_confirmed(session.id)
            await self._uow.commit()

        message = TrainerNotificationMessage(
            sport_direction_name=session.sport_direction_name,
            group_name=session.group_name,
            starts_at=session.starts_at.astimezone(self._club_timezone),
            ends_at=session.ends_at.astimezone(self._club_timezone),
            expected_count=expected_count,
            confirmed_count=confirmed_count,
        )
        try:
            await self._notifier.send(
                telegram_id=session.trainer_telegram_id,
                message=message,
            )
        except PermanentTrainerNotifierError:
            await self._mark_failed(
                session=session,
                idempotency_key=key,
                attempts=claim.attempts,
                reference_now=reference_now,
            )
            return NotifyTrainerBeforeSessionResult(
                outcome=NotifyTrainerOutcome.TERMINAL_FAILED,
                training_session_id=session.id,
                attempts=claim.attempts,
            )
        except RetryableTrainerNotifierError as error:
            retry_after = error.retry_after_seconds
            retry_misses_deadline = (
                retry_after is not None
                and reference_now + timedelta(seconds=retry_after)
                >= session.starts_at
            )
            if claim.attempts >= MAX_DELIVERY_ATTEMPTS or retry_misses_deadline:
                await self._mark_failed(
                    session=session,
                    idempotency_key=key,
                    attempts=claim.attempts,
                    reference_now=reference_now,
                )
                return NotifyTrainerBeforeSessionResult(
                    outcome=NotifyTrainerOutcome.TERMINAL_FAILED,
                    training_session_id=session.id,
                    attempts=claim.attempts,
                )
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=session.id,
                starts_at=session.starts_at,
                retry_after_seconds=retry_after,
            ) from error

        async with self._uow:
            await self._deliveries.mark_sent(
                idempotency_key=key,
                attempts=claim.attempts,
                sent_at=reference_now,
            )
            await self._uow.commit()
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.SENT,
            training_session_id=session.id,
            attempts=claim.attempts,
        )

    async def _terminalize_without_send(
        self,
        *,
        session: TrainerNotificationSession,
        idempotency_key: str,
        reference_now: datetime,
    ) -> None:
        await self._deliveries.mark_failed(
            training_session_id=session.id,
            recipient_user_id=session.trainer_id,
            scheduled_at=session.starts_at - NOTIFY_BEFORE,
            idempotency_key=idempotency_key,
            expected_attempts=None,
            reference_now=reference_now,
        )
        await self._uow.commit()

    async def _mark_failed(
        self,
        *,
        session: TrainerNotificationSession,
        idempotency_key: str,
        attempts: int,
        reference_now: datetime,
    ) -> None:
        async with self._uow:
            await self._deliveries.mark_failed(
                training_session_id=session.id,
                recipient_user_id=session.trainer_id,
                scheduled_at=session.starts_at - NOTIFY_BEFORE,
                idempotency_key=idempotency_key,
                expected_attempts=attempts,
                reference_now=reference_now,
            )
            await self._uow.commit()

    @staticmethod
    def _result(
        command: NotifyTrainerBeforeSessionCommand,
        outcome: NotifyTrainerOutcome,
    ) -> NotifyTrainerBeforeSessionResult:
        return NotifyTrainerBeforeSessionResult(
            outcome=outcome,
            training_session_id=command.training_session_id,
        )

    @staticmethod
    def _claim_result(
        command: NotifyTrainerBeforeSessionCommand,
        outcome: TrainerNotificationClaimOutcome,
    ) -> NotifyTrainerBeforeSessionResult | None:
        mapped = {
            TrainerNotificationClaimOutcome.ALREADY_SENT: (
                NotifyTrainerOutcome.ALREADY_SENT
            ),
            TrainerNotificationClaimOutcome.TERMINAL_FAILED: (
                NotifyTrainerOutcome.TERMINAL_FAILED
            ),
            TrainerNotificationClaimOutcome.IN_PROGRESS: (
                NotifyTrainerOutcome.IN_PROGRESS
            ),
        }.get(outcome)
        return (
            NotifyTrainerBeforeSessionInteractor._result(command, mapped)
            if mapped is not None
            else None
        )
