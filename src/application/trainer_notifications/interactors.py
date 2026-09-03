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
    TrainerNotificationClaim,
    TrainerNotificationClaimOutcome,
    TrainerNotificationMessage,
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
            preliminary_session = await self._reader.get_session(
                command.training_session_id
            )
            if preliminary_session is None:
                return self._result(
                    command,
                    NotifyTrainerOutcome.SESSION_NOT_FOUND,
                )

            key = trainer_notification_idempotency_key(preliminary_session.id)
            if preliminary_session.starts_at > reference_now + NOTIFY_BEFORE:
                released = False
                if command.notification_id is not None:
                    released = await self._deliveries.release_pending(
                        notification_id=command.notification_id,
                        idempotency_key=key,
                        expected_attempts=command.delivery_attempt - 1,
                    )
                elif command.delivery_attempt == 1:
                    released = await self._deliveries.release_stale_pending(
                        idempotency_key=key,
                        stale_pending_before=(
                            reference_now - STALE_PENDING_AFTER
                        ),
                    )
                if released:
                    await self._uow.commit()
                return self._result(
                    command,
                    NotifyTrainerOutcome.NOT_DUE,
                    attempts=max(command.delivery_attempt - 1, 0),
                )

            if not preliminary_session.trainer_user_exists:
                return self._result(
                    command,
                    NotifyTrainerOutcome.TRAINER_UNAVAILABLE,
                )

            claim = await self._deliveries.claim(
                notification_type=NOTIFICATION_TYPE,
                training_session_id=preliminary_session.id,
                recipient_user_id=preliminary_session.trainer_id,
                scheduled_at=preliminary_session.starts_at - NOTIFY_BEFORE,
                idempotency_key=key,
                delivery_attempt=command.delivery_attempt,
                notification_id=command.notification_id,
                stale_pending_before=reference_now - STALE_PENDING_AFTER,
                max_attempts=MAX_DELIVERY_ATTEMPTS,
                reference_now=reference_now,
            )
            claim_result = self._claim_result(claim.outcome)
            if claim_result is not None:
                await self._uow.commit()
                return NotifyTrainerBeforeSessionResult(
                    outcome=claim_result,
                    training_session_id=command.training_session_id,
                    attempts=claim.attempts,
                    notification_id=claim.notification_id,
                )
            if claim.notification_id is None:
                return self._result(command, NotifyTrainerOutcome.IN_PROGRESS)
            await self._uow.commit()

        async with self._uow:
            session = await self._reader.get_session(command.training_session_id)
            if session is None:
                return await self._terminal_result(
                    command=command,
                    claim=claim,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyTrainerOutcome.SESSION_NOT_FOUND,
                )
            if session.status is TrainingSessionStatus.CANCELLED:
                return await self._terminal_result(
                    command=command,
                    claim=claim,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyTrainerOutcome.CANCELLED,
                )
            if reference_now >= session.starts_at:
                return await self._terminal_result(
                    command=command,
                    claim=claim,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyTrainerOutcome.SESSION_STARTED,
                )
            if session.starts_at > reference_now + NOTIFY_BEFORE:
                released = await self._deliveries.release_pending(
                    notification_id=claim.notification_id,
                    idempotency_key=key,
                    expected_attempts=claim.attempts,
                )
                if released:
                    await self._uow.commit()
                return self._owned_result(
                    command,
                    claim,
                    (
                        NotifyTrainerOutcome.NOT_DUE
                        if released
                        else NotifyTrainerOutcome.IN_PROGRESS
                    ),
                )
            if not session.trainer_user_exists or session.trainer_telegram_id is None:
                return await self._terminal_result(
                    command=command,
                    claim=claim,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyTrainerOutcome.TRAINER_UNAVAILABLE,
                )
            refreshed = await self._deliveries.refresh_pending(
                notification_id=claim.notification_id,
                idempotency_key=key,
                expected_attempts=claim.attempts,
                recipient_user_id=session.trainer_id,
                scheduled_at=session.starts_at - NOTIFY_BEFORE,
                reference_now=reference_now,
            )
            if not refreshed:
                return self._owned_result(
                    command,
                    claim,
                    NotifyTrainerOutcome.IN_PROGRESS,
                )
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
            failed = await self._mark_failed(
                notification_id=claim.notification_id,
                idempotency_key=key,
                attempts=claim.attempts,
                reference_now=reference_now,
            )
            return NotifyTrainerBeforeSessionResult(
                outcome=(
                    NotifyTrainerOutcome.TERMINAL_FAILED
                    if failed
                    else NotifyTrainerOutcome.IN_PROGRESS
                ),
                training_session_id=session.id,
                attempts=claim.attempts,
                notification_id=claim.notification_id,
            )
        except RetryableTrainerNotifierError as error:
            retry_after = error.retry_after_seconds
            retry_misses_deadline = (
                retry_after is not None
                and reference_now + timedelta(seconds=retry_after)
                >= session.starts_at
            )
            if claim.attempts >= MAX_DELIVERY_ATTEMPTS or retry_misses_deadline:
                failed = await self._mark_failed(
                    notification_id=claim.notification_id,
                    idempotency_key=key,
                    attempts=claim.attempts,
                    reference_now=reference_now,
                )
                return NotifyTrainerBeforeSessionResult(
                    outcome=(
                        NotifyTrainerOutcome.TERMINAL_FAILED
                        if failed
                        else NotifyTrainerOutcome.IN_PROGRESS
                    ),
                    training_session_id=session.id,
                    attempts=claim.attempts,
                    notification_id=claim.notification_id,
                )
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=session.id,
                notification_id=claim.notification_id,
                delivery_attempt=claim.attempts,
                starts_at=session.starts_at,
                retry_after_seconds=retry_after,
            ) from error

        async with self._uow:
            sent = await self._deliveries.mark_sent(
                notification_id=claim.notification_id,
                idempotency_key=key,
                attempts=claim.attempts,
                sent_at=reference_now,
            )
            if sent:
                await self._uow.commit()
        return NotifyTrainerBeforeSessionResult(
            outcome=(
                NotifyTrainerOutcome.SENT
                if sent
                else NotifyTrainerOutcome.IN_PROGRESS
            ),
            training_session_id=session.id,
            attempts=claim.attempts,
            notification_id=claim.notification_id,
        )

    async def _terminal_result(
        self,
        *,
        command: NotifyTrainerBeforeSessionCommand,
        claim: TrainerNotificationClaim,
        idempotency_key: str,
        reference_now: datetime,
        outcome: NotifyTrainerOutcome,
    ) -> NotifyTrainerBeforeSessionResult:
        if claim.notification_id is None:
            return self._result(command, NotifyTrainerOutcome.IN_PROGRESS)
        failed = await self._deliveries.mark_failed(
            notification_id=claim.notification_id,
            idempotency_key=idempotency_key,
            expected_attempts=claim.attempts,
            reference_now=reference_now,
        )
        if failed:
            await self._uow.commit()
        return self._owned_result(
            command,
            claim,
            outcome if failed else NotifyTrainerOutcome.IN_PROGRESS,
        )

    async def _mark_failed(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        attempts: int,
        reference_now: datetime,
    ) -> bool:
        async with self._uow:
            failed = await self._deliveries.mark_failed(
                notification_id=notification_id,
                idempotency_key=idempotency_key,
                expected_attempts=attempts,
                reference_now=reference_now,
            )
            if failed:
                await self._uow.commit()
            return failed

    @staticmethod
    def _result(
        command: NotifyTrainerBeforeSessionCommand,
        outcome: NotifyTrainerOutcome,
        *,
        attempts: int = 0,
    ) -> NotifyTrainerBeforeSessionResult:
        return NotifyTrainerBeforeSessionResult(
            outcome=outcome,
            training_session_id=command.training_session_id,
            attempts=attempts,
            notification_id=command.notification_id,
        )

    @staticmethod
    def _claim_result(
        outcome: TrainerNotificationClaimOutcome,
    ) -> NotifyTrainerOutcome | None:
        return {
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

    @staticmethod
    def _owned_result(
        command: NotifyTrainerBeforeSessionCommand,
        claim: TrainerNotificationClaim,
        outcome: NotifyTrainerOutcome,
    ) -> NotifyTrainerBeforeSessionResult:
        return NotifyTrainerBeforeSessionResult(
            outcome=outcome,
            training_session_id=command.training_session_id,
            attempts=claim.attempts,
            notification_id=claim.notification_id,
        )
