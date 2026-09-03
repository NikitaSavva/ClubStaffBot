from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from application.notification_delivery import (
    NotificationClaim,
    NotificationClaimOutcome,
    NotificationDeliveryRepository,
)
from infrastructure.database.models import NotificationModel, NotificationStatus


class SqlAlchemyNotificationDeliveryRepository(NotificationDeliveryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        *,
        notification_type: str,
        training_session_id: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
        delivery_attempt: int,
        notification_id: int | None,
        stale_pending_before: datetime,
        max_attempts: int,
        reference_now: datetime,
    ) -> NotificationClaim:
        if delivery_attempt == 1:
            inserted = (
                await self._session.execute(
                    insert(NotificationModel)
                    .values(
                        recipient_user_id=recipient_user_id,
                        training_session_id=training_session_id,
                        type=notification_type,
                        scheduled_at=scheduled_at,
                        sent_at=None,
                        status=NotificationStatus.PENDING,
                        idempotency_key=idempotency_key,
                        attempts=1,
                        created_at=reference_now,
                        updated_at=reference_now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=(NotificationModel.idempotency_key,)
                    )
                    .returning(NotificationModel.id, NotificationModel.attempts)
                )
            ).one_or_none()
            if inserted is not None:
                return NotificationClaim(
                    outcome=NotificationClaimOutcome.ACQUIRED,
                    attempts=inserted.attempts,
                    notification_id=inserted.id,
                )

            reclaimed = (
                await self._session.execute(
                    update(NotificationModel)
                    .where(
                        NotificationModel.idempotency_key == idempotency_key,
                        NotificationModel.status == NotificationStatus.PENDING,
                        NotificationModel.updated_at <= stale_pending_before,
                        NotificationModel.attempts < max_attempts,
                    )
                    .values(
                        recipient_user_id=recipient_user_id,
                        training_session_id=training_session_id,
                        type=notification_type,
                        scheduled_at=scheduled_at,
                        attempts=NotificationModel.attempts + 1,
                        updated_at=reference_now,
                    )
                    .returning(NotificationModel.id, NotificationModel.attempts)
                )
            ).one_or_none()
            if reclaimed is not None:
                return NotificationClaim(
                    outcome=NotificationClaimOutcome.ACQUIRED,
                    attempts=reclaimed.attempts,
                    notification_id=reclaimed.id,
                )

            await self._terminalize_exhausted_stale(
                idempotency_key=idempotency_key,
                stale_pending_before=stale_pending_before,
                max_attempts=max_attempts,
                reference_now=reference_now,
            )
        else:
            if notification_id is None:
                return NotificationClaim(
                    outcome=NotificationClaimOutcome.IN_PROGRESS,
                    attempts=0,
                    notification_id=None,
                )
            resumed = (
                await self._session.execute(
                    update(NotificationModel)
                    .where(
                        NotificationModel.id == notification_id,
                        NotificationModel.idempotency_key == idempotency_key,
                        NotificationModel.status == NotificationStatus.PENDING,
                        NotificationModel.attempts == delivery_attempt - 1,
                    )
                    .values(
                        recipient_user_id=recipient_user_id,
                        training_session_id=training_session_id,
                        type=notification_type,
                        scheduled_at=scheduled_at,
                        attempts=delivery_attempt,
                        updated_at=reference_now,
                    )
                    .returning(NotificationModel.id, NotificationModel.attempts)
                )
            ).one_or_none()
            if resumed is not None:
                return NotificationClaim(
                    outcome=NotificationClaimOutcome.ACQUIRED,
                    attempts=resumed.attempts,
                    notification_id=resumed.id,
                )

        row = (
            await self._session.execute(
                select(
                    NotificationModel.id,
                    NotificationModel.status,
                    NotificationModel.attempts,
                ).where(NotificationModel.idempotency_key == idempotency_key)
            )
        ).one_or_none()
        if row is None:
            return NotificationClaim(
                outcome=NotificationClaimOutcome.IN_PROGRESS,
                attempts=0,
                notification_id=None,
            )
        outcome = {
            NotificationStatus.SENT: NotificationClaimOutcome.ALREADY_SENT,
            NotificationStatus.FAILED: NotificationClaimOutcome.TERMINAL_FAILED,
            NotificationStatus.PENDING: NotificationClaimOutcome.IN_PROGRESS,
        }[row.status]
        return NotificationClaim(
            outcome=outcome,
            attempts=row.attempts,
            notification_id=row.id,
        )

    async def mark_sent(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        attempts: int,
        sent_at: datetime,
    ) -> bool:
        sent_notification_id = await self._session.scalar(
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.attempts == attempts,
            )
            .values(
                status=NotificationStatus.SENT,
                sent_at=sent_at,
                updated_at=sent_at,
            )
            .returning(NotificationModel.id)
        )
        return sent_notification_id is not None

    async def mark_failed(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        reference_now: datetime,
    ) -> bool:
        failed_notification_id = await self._session.scalar(
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.attempts == expected_attempts,
            )
            .values(status=NotificationStatus.FAILED, updated_at=reference_now)
            .returning(NotificationModel.id)
        )
        return failed_notification_id is not None

    async def refresh_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        reference_now: datetime,
    ) -> bool:
        refreshed_id = await self._session.scalar(
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.attempts == expected_attempts,
            )
            .values(
                recipient_user_id=recipient_user_id,
                scheduled_at=scheduled_at,
                updated_at=reference_now,
            )
            .returning(NotificationModel.id)
        )
        return refreshed_id is not None

    async def release_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
    ) -> bool:
        released_notification_id = await self._session.scalar(
            delete(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.attempts == expected_attempts,
            )
            .returning(NotificationModel.id)
        )
        return released_notification_id is not None

    async def release_stale_pending(
        self,
        *,
        idempotency_key: str,
        stale_pending_before: datetime,
    ) -> bool:
        notification_id = await self._session.scalar(
            delete(NotificationModel)
            .where(
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.updated_at <= stale_pending_before,
            )
            .returning(NotificationModel.id)
        )
        return notification_id is not None

    async def _terminalize_exhausted_stale(
        self,
        *,
        idempotency_key: str,
        stale_pending_before: datetime,
        max_attempts: int,
        reference_now: datetime,
    ) -> None:
        await self._session.execute(
            update(NotificationModel)
            .where(
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.updated_at <= stale_pending_before,
                NotificationModel.attempts >= max_attempts,
            )
            .values(status=NotificationStatus.FAILED, updated_at=reference_now)
        )
