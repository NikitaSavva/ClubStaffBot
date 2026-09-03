from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from application.athlete_notifications.commands import (
    NotifyAthleteBeforeSessionCommand,
)
from application.athlete_notifications.dto import (
    AthleteNotificationMessage,
    FindAthleteNotificationCandidatesResult,
    NotifyAthleteBeforeSessionResult,
    NotifyAthleteOutcome,
)
from application.athlete_notifications.errors import (
    RetryableAthleteNotificationDeliveryError,
)
from application.athlete_notifications.ports import (
    AthleteNotificationReader,
    AthleteNotifier,
)
from application.common import Clock, UnitOfWork
from application.notification_delivery import (
    NotificationClaim,
    NotificationClaimOutcome,
    NotificationDeliveryRepository,
    PermanentNotificationSenderError,
    RetryableNotificationSenderError,
)
from domain.club import TrainingSessionStatus

NOTIFICATION_TYPE = "ATHLETE_SESSION_MINUS_2H"
NOTIFY_BEFORE = timedelta(hours=2)
REMINDER_GRACE_WINDOW = timedelta(minutes=10)
STALE_PENDING_AFTER = timedelta(minutes=10)
MAX_DELIVERY_ATTEMPTS = 4


def athlete_notification_idempotency_key(
    training_session_id: int,
    athlete_id: int,
) -> str:
    return f"{NOTIFICATION_TYPE}:{training_session_id}:{athlete_id}"


def default_retry_delay_seconds(delivery_attempt: int) -> int:
    return 30 * (1 << (delivery_attempt - 1))


class FindAthletesForSessionReminderInteractor:
    def __init__(self, reader: AthleteNotificationReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    async def __call__(self) -> FindAthleteNotificationCandidatesResult:
        reference_now = self._clock.now()
        candidates = await self._reader.find_due_candidates(
            reference_now=reference_now,
            notify_before_seconds=int(NOTIFY_BEFORE.total_seconds()),
            grace_window_seconds=int(REMINDER_GRACE_WINDOW.total_seconds()),
            stale_pending_before=reference_now - STALE_PENDING_AFTER,
        )
        return FindAthleteNotificationCandidatesResult(
            reference_now=reference_now,
            candidates=candidates,
        )


class NotifyAthleteBeforeSessionInteractor:
    def __init__(
        self,
        reader: AthleteNotificationReader,
        delivery_repository: NotificationDeliveryRepository,
        notifier: AthleteNotifier,
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
        command: NotifyAthleteBeforeSessionCommand,
    ) -> NotifyAthleteBeforeSessionResult:
        reference_now = self._clock.now()
        key = athlete_notification_idempotency_key(
            command.training_session_id,
            command.athlete_id,
        )
        async with self._uow:
            preliminary_session = await self._reader.get_session(
                command.training_session_id
            )
            if preliminary_session is None:
                return await self._terminal_existing(
                    command=command,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyAthleteOutcome.SESSION_NOT_FOUND,
                )

            due_at = preliminary_session.starts_at - NOTIFY_BEFORE
            if reference_now < due_at:
                return await self._release_existing(
                    command=command,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyAthleteOutcome.NOT_DUE,
                )

            recipient = await self._reader.get_eligible_recipient(
                athlete_id=command.athlete_id,
                training_group_id=preliminary_session.group_id,
                reference_now=reference_now,
            )
            if recipient is None:
                return await self._release_existing(
                    command=command,
                    idempotency_key=key,
                    reference_now=reference_now,
                    outcome=NotifyAthleteOutcome.ATHLETE_INELIGIBLE,
                )

            claim = await self._deliveries.claim(
                notification_type=NOTIFICATION_TYPE,
                training_session_id=preliminary_session.id,
                recipient_user_id=recipient.user_id,
                scheduled_at=due_at,
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
                return self._owned_result(command, claim, claim_result)
            if claim.notification_id is None:
                return self._result(command, NotifyAthleteOutcome.IN_PROGRESS)
            await self._uow.commit()

        async with self._uow:
            session = await self._reader.get_session(command.training_session_id)
            if session is None:
                return await self._terminal_claim(
                    command, claim, key, reference_now,
                    NotifyAthleteOutcome.SESSION_NOT_FOUND,
                )
            due_at = session.starts_at - NOTIFY_BEFORE
            window_ends_at = due_at + REMINDER_GRACE_WINDOW
            if session.status is TrainingSessionStatus.CANCELLED:
                return await self._terminal_claim(
                    command, claim, key, reference_now,
                    NotifyAthleteOutcome.CANCELLED,
                )
            if reference_now >= session.starts_at:
                return await self._terminal_claim(
                    command, claim, key, reference_now,
                    NotifyAthleteOutcome.SESSION_STARTED,
                )
            if reference_now < due_at:
                return await self._release_claim(
                    command, claim, key, NotifyAthleteOutcome.NOT_DUE
                )
            if reference_now >= window_ends_at:
                return await self._terminal_claim(
                    command, claim, key, reference_now,
                    NotifyAthleteOutcome.WINDOW_EXPIRED,
                )

            recipient = await self._reader.get_eligible_recipient(
                athlete_id=command.athlete_id,
                training_group_id=session.group_id,
                reference_now=reference_now,
            )
            if recipient is None:
                return await self._release_claim(
                    command,
                    claim,
                    key,
                    NotifyAthleteOutcome.ATHLETE_INELIGIBLE,
                )
            if recipient.telegram_id is None:
                return await self._terminal_claim(
                    command, claim, key, reference_now,
                    NotifyAthleteOutcome.TELEGRAM_UNAVAILABLE,
                )
            refreshed = await self._deliveries.refresh_pending(
                notification_id=claim.notification_id,
                idempotency_key=key,
                expected_attempts=claim.attempts,
                recipient_user_id=recipient.user_id,
                scheduled_at=due_at,
                reference_now=reference_now,
            )
            if not refreshed:
                return self._owned_result(
                    command, claim, NotifyAthleteOutcome.IN_PROGRESS
                )
            await self._uow.commit()

        message = AthleteNotificationMessage(
            sport_direction_name=session.sport_direction_name,
            group_name=session.group_name,
            starts_at=session.starts_at.astimezone(self._club_timezone),
            ends_at=session.ends_at.astimezone(self._club_timezone),
        )
        try:
            await self._notifier.send(
                telegram_id=recipient.telegram_id,
                message=message,
            )
        except PermanentNotificationSenderError:
            return await self._mark_failed_result(
                command=command,
                claim=claim,
                idempotency_key=key,
                reference_now=reference_now,
            )
        except RetryableNotificationSenderError as error:
            retry_delay = error.retry_after_seconds or default_retry_delay_seconds(
                claim.attempts
            )
            retry_misses_window = (
                reference_now + timedelta(seconds=retry_delay)
                >= window_ends_at
            )
            if claim.attempts >= MAX_DELIVERY_ATTEMPTS or retry_misses_window:
                return await self._mark_failed_result(
                    command=command,
                    claim=claim,
                    idempotency_key=key,
                    reference_now=reference_now,
                )
            raise RetryableAthleteNotificationDeliveryError(
                training_session_id=session.id,
                athlete_id=command.athlete_id,
                notification_id=claim.notification_id,
                delivery_attempt=claim.attempts,
                reminder_window_ends_at=window_ends_at,
                retry_after_seconds=error.retry_after_seconds,
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
        return self._owned_result(
            command,
            claim,
            NotifyAthleteOutcome.SENT if sent else NotifyAthleteOutcome.IN_PROGRESS,
        )

    async def _terminal_existing(
        self,
        *,
        command: NotifyAthleteBeforeSessionCommand,
        idempotency_key: str,
        reference_now: datetime,
        outcome: NotifyAthleteOutcome,
    ) -> NotifyAthleteBeforeSessionResult:
        if command.notification_id is None:
            return self._result(command, outcome)
        failed = await self._deliveries.mark_failed(
            notification_id=command.notification_id,
            idempotency_key=idempotency_key,
            expected_attempts=command.delivery_attempt - 1,
            reference_now=reference_now,
        )
        if failed:
            await self._uow.commit()
        return self._result(
            command,
            outcome if failed else NotifyAthleteOutcome.IN_PROGRESS,
            attempts=command.delivery_attempt - 1,
        )

    async def _release_existing(
        self,
        *,
        command: NotifyAthleteBeforeSessionCommand,
        idempotency_key: str,
        reference_now: datetime,
        outcome: NotifyAthleteOutcome,
    ) -> NotifyAthleteBeforeSessionResult:
        if command.notification_id is not None:
            released = await self._deliveries.release_pending(
                notification_id=command.notification_id,
                idempotency_key=idempotency_key,
                expected_attempts=command.delivery_attempt - 1,
            )
        else:
            released = await self._deliveries.release_stale_pending(
                idempotency_key=idempotency_key,
                stale_pending_before=reference_now - STALE_PENDING_AFTER,
            )
        if released:
            await self._uow.commit()
        return self._result(
            command,
            outcome if released or command.notification_id is None
            else NotifyAthleteOutcome.IN_PROGRESS,
            attempts=max(command.delivery_attempt - 1, 0),
        )

    async def _terminal_claim(
        self,
        command: NotifyAthleteBeforeSessionCommand,
        claim: NotificationClaim,
        idempotency_key: str,
        reference_now: datetime,
        outcome: NotifyAthleteOutcome,
    ) -> NotifyAthleteBeforeSessionResult:
        if claim.notification_id is None:
            return self._result(command, NotifyAthleteOutcome.IN_PROGRESS)
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
            outcome if failed else NotifyAthleteOutcome.IN_PROGRESS,
        )

    async def _release_claim(
        self,
        command: NotifyAthleteBeforeSessionCommand,
        claim: NotificationClaim,
        idempotency_key: str,
        outcome: NotifyAthleteOutcome,
    ) -> NotifyAthleteBeforeSessionResult:
        if claim.notification_id is None:
            return self._result(command, NotifyAthleteOutcome.IN_PROGRESS)
        released = await self._deliveries.release_pending(
            notification_id=claim.notification_id,
            idempotency_key=idempotency_key,
            expected_attempts=claim.attempts,
        )
        if released:
            await self._uow.commit()
        return self._owned_result(
            command,
            claim,
            outcome if released else NotifyAthleteOutcome.IN_PROGRESS,
        )

    async def _mark_failed_result(
        self,
        *,
        command: NotifyAthleteBeforeSessionCommand,
        claim: NotificationClaim,
        idempotency_key: str,
        reference_now: datetime,
    ) -> NotifyAthleteBeforeSessionResult:
        if claim.notification_id is None:
            return self._result(command, NotifyAthleteOutcome.IN_PROGRESS)
        async with self._uow:
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
            NotifyAthleteOutcome.TERMINAL_FAILED
            if failed else NotifyAthleteOutcome.IN_PROGRESS,
        )

    @staticmethod
    def _claim_result(outcome: NotificationClaimOutcome) -> NotifyAthleteOutcome | None:
        return {
            NotificationClaimOutcome.ALREADY_SENT: NotifyAthleteOutcome.ALREADY_SENT,
            NotificationClaimOutcome.TERMINAL_FAILED: (
                NotifyAthleteOutcome.TERMINAL_FAILED
            ),
            NotificationClaimOutcome.IN_PROGRESS: NotifyAthleteOutcome.IN_PROGRESS,
        }.get(outcome)

    @staticmethod
    def _result(
        command: NotifyAthleteBeforeSessionCommand,
        outcome: NotifyAthleteOutcome,
        *,
        attempts: int = 0,
    ) -> NotifyAthleteBeforeSessionResult:
        return NotifyAthleteBeforeSessionResult(
            outcome=outcome,
            training_session_id=command.training_session_id,
            athlete_id=command.athlete_id,
            attempts=attempts,
            notification_id=command.notification_id,
        )

    @staticmethod
    def _owned_result(
        command: NotifyAthleteBeforeSessionCommand,
        claim: NotificationClaim,
        outcome: NotifyAthleteOutcome,
    ) -> NotifyAthleteBeforeSessionResult:
        return NotifyAthleteBeforeSessionResult(
            outcome=outcome,
            training_session_id=command.training_session_id,
            athlete_id=command.athlete_id,
            attempts=claim.attempts,
            notification_id=claim.notification_id,
        )
