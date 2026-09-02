from datetime import datetime, timedelta

from sqlalchemy import and_, delete, distinct, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from application.trainer_notifications import (
    TrainerNotificationClaim,
    TrainerNotificationClaimOutcome,
    TrainerNotificationDeliveryRepository,
    TrainerNotificationReader,
    TrainerNotificationSession,
)
from domain.attendance import AttendanceStatus
from domain.club import TrainingSessionStatus
from domain.subscriptions import (
    SubscriptionAccessScope,
    SubscriptionStatus,
)
from infrastructure.database.models import (
    AttendanceModel,
    GroupNameModel,
    NotificationModel,
    NotificationStatus,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)

NOTIFICATION_TYPE = "TRAINER_SESSION_MINUS_5"


class SqlAlchemyTrainerNotificationReader(TrainerNotificationReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_due_session_ids(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[int, ...]:
        blocking_notification = exists(
            select(NotificationModel.id).where(
                NotificationModel.training_session_id
                == TrainingSessionModel.id,
                NotificationModel.type == NOTIFICATION_TYPE,
                or_(
                    NotificationModel.status.in_(
                        (NotificationStatus.SENT, NotificationStatus.FAILED)
                    ),
                    and_(
                        NotificationModel.status == NotificationStatus.PENDING,
                        NotificationModel.updated_at > stale_pending_before,
                    ),
                ),
            )
        )
        stale_pending_notification = exists(
            select(NotificationModel.id).where(
                NotificationModel.training_session_id
                == TrainingSessionModel.id,
                NotificationModel.type == NOTIFICATION_TYPE,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.updated_at <= stale_pending_before,
            )
        )
        due = and_(
            TrainingSessionModel.starts_at > reference_now,
            TrainingSessionModel.starts_at
            <= reference_now + timedelta(seconds=notify_before_seconds),
            TrainingSessionModel.status != TrainingSessionStatus.CANCELLED,
        )
        session_ids = await self._session.scalars(
            select(TrainingSessionModel.id)
            .where(
                or_(
                    and_(due, ~blocking_notification),
                    stale_pending_notification,
                )
            )
            .order_by(
                TrainingSessionModel.starts_at.asc(),
                TrainingSessionModel.id.asc(),
            )
        )
        return tuple(session_ids)

    async def get_session(
        self,
        training_session_id: int,
    ) -> TrainerNotificationSession | None:
        row = (
            await self._session.execute(
                select(
                    TrainingSessionModel.id,
                    TrainingSessionModel.group_id,
                    TrainingSessionModel.trainer_id,
                    TrainingSessionModel.starts_at,
                    TrainingSessionModel.ends_at,
                    TrainingSessionModel.status,
                    TrainingGroupModel.group_type,
                    SportDirectionModel.name.label("sport_direction_name"),
                    GroupNameModel.name.label("group_name"),
                    UserModel.id.label("trainer_user_id"),
                    UserModel.telegram_id.label("trainer_telegram_id"),
                )
                .select_from(TrainingSessionModel)
                .join(
                    TrainingGroupModel,
                    TrainingGroupModel.id == TrainingSessionModel.group_id,
                )
                .join(
                    SportDirectionModel,
                    SportDirectionModel.id == TrainingGroupModel.direction_id,
                )
                .join(
                    GroupNameModel,
                    GroupNameModel.id == TrainingGroupModel.name_id,
                )
                .outerjoin(
                    UserModel,
                    UserModel.id == TrainingSessionModel.trainer_id,
                )
                .where(TrainingSessionModel.id == training_session_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return TrainerNotificationSession(
            id=row.id,
            group_id=row.group_id,
            trainer_id=row.trainer_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            group_type=row.group_type,
            sport_direction_name=row.sport_direction_name,
            group_name=row.group_name,
            trainer_user_exists=row.trainer_user_id is not None,
            trainer_telegram_id=row.trainer_telegram_id,
        )

    async def count_expected(
        self,
        *,
        training_group_id: int,
        group_is_regular: bool,
        reference_now: datetime,
    ) -> int:
        access_filter = and_(
            SubscriptionPlanModel.access_scope
            == SubscriptionAccessScope.SPECIFIC_GROUP,
            SubscriptionModel.group_id == training_group_id,
        )
        if group_is_regular:
            access_filter = or_(
                access_filter,
                SubscriptionPlanModel.access_scope
                == SubscriptionAccessScope.ALL_REGULAR_GROUPS,
            )

        count = await self._session.scalar(
            select(func.count(distinct(SubscriptionModel.athlete_id)))
            .select_from(SubscriptionModel)
            .join(
                SubscriptionPlanModel,
                SubscriptionPlanModel.id == SubscriptionModel.plan_id,
            )
            .where(
                SubscriptionModel.status == SubscriptionStatus.ACTIVE,
                SubscriptionModel.starts_at <= reference_now,
                reference_now < SubscriptionModel.expires_at,
                or_(
                    SubscriptionModel.remaining_visits.is_(None),
                    SubscriptionModel.remaining_visits > 0,
                ),
                access_filter,
            )
        )
        return count or 0

    async def count_confirmed(self, training_session_id: int) -> int:
        count = await self._session.scalar(
            select(func.count(AttendanceModel.id)).where(
                AttendanceModel.training_session_id == training_session_id,
                AttendanceModel.status == AttendanceStatus.CONFIRMED,
            )
        )
        return count or 0


class SqlAlchemyTrainerNotificationDeliveryRepository(
    TrainerNotificationDeliveryRepository
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        *,
        training_session_id: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
        delivery_attempt: int,
        stale_pending_before: datetime,
        max_attempts: int,
        reference_now: datetime,
    ) -> TrainerNotificationClaim:
        if delivery_attempt == 1:
            inserted_attempts = await self._session.scalar(
                insert(NotificationModel)
                .values(
                    recipient_user_id=recipient_user_id,
                    training_session_id=training_session_id,
                    type=NOTIFICATION_TYPE,
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
                .returning(NotificationModel.attempts)
            )
            if inserted_attempts is not None:
                return TrainerNotificationClaim(
                    outcome=TrainerNotificationClaimOutcome.ACQUIRED,
                    attempts=inserted_attempts,
                )

            reclaimed_attempts = await self._session.scalar(
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
                    scheduled_at=scheduled_at,
                    attempts=NotificationModel.attempts + 1,
                    updated_at=reference_now,
                )
                .returning(NotificationModel.attempts)
            )
            if reclaimed_attempts is not None:
                return TrainerNotificationClaim(
                    outcome=TrainerNotificationClaimOutcome.ACQUIRED,
                    attempts=reclaimed_attempts,
                )

            await self._terminalize_exhausted_stale(
                idempotency_key=idempotency_key,
                stale_pending_before=stale_pending_before,
                max_attempts=max_attempts,
                reference_now=reference_now,
            )
        else:
            resumed_attempts = await self._session.scalar(
                update(NotificationModel)
                .where(
                    NotificationModel.idempotency_key == idempotency_key,
                    NotificationModel.status == NotificationStatus.PENDING,
                    NotificationModel.attempts == delivery_attempt - 1,
                )
                .values(
                    recipient_user_id=recipient_user_id,
                    training_session_id=training_session_id,
                    scheduled_at=scheduled_at,
                    attempts=delivery_attempt,
                    updated_at=reference_now,
                )
                .returning(NotificationModel.attempts)
            )
            if resumed_attempts is not None:
                return TrainerNotificationClaim(
                    outcome=TrainerNotificationClaimOutcome.ACQUIRED,
                    attempts=resumed_attempts,
                )

        row = (
            await self._session.execute(
                select(NotificationModel.status, NotificationModel.attempts)
                .where(NotificationModel.idempotency_key == idempotency_key)
            )
        ).one()
        outcome = {
            NotificationStatus.SENT: (
                TrainerNotificationClaimOutcome.ALREADY_SENT
            ),
            NotificationStatus.FAILED: (
                TrainerNotificationClaimOutcome.TERMINAL_FAILED
            ),
            NotificationStatus.PENDING: (
                TrainerNotificationClaimOutcome.IN_PROGRESS
            ),
        }[row.status]
        return TrainerNotificationClaim(outcome=outcome, attempts=row.attempts)

    async def mark_sent(
        self,
        *,
        idempotency_key: str,
        attempts: int,
        sent_at: datetime,
    ) -> bool:
        notification_id = await self._session.scalar(
            update(NotificationModel)
            .where(
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
        return notification_id is not None

    async def mark_failed(
        self,
        *,
        training_session_id: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
        expected_attempts: int | None,
        reference_now: datetime,
    ) -> bool:
        statement = insert(NotificationModel).values(
            recipient_user_id=recipient_user_id,
            training_session_id=training_session_id,
            type=NOTIFICATION_TYPE,
            scheduled_at=scheduled_at,
            sent_at=None,
            status=NotificationStatus.FAILED,
            idempotency_key=idempotency_key,
            attempts=expected_attempts or 0,
            created_at=reference_now,
            updated_at=reference_now,
        )
        update_where = NotificationModel.status == NotificationStatus.PENDING
        if expected_attempts is not None:
            update_where = and_(
                update_where,
                NotificationModel.attempts == expected_attempts,
            )
        notification_id = await self._session.scalar(
            statement.on_conflict_do_update(
                index_elements=(NotificationModel.idempotency_key,),
                set_={
                    "status": NotificationStatus.FAILED,
                    "updated_at": reference_now,
                },
                where=update_where,
            ).returning(NotificationModel.id)
        )
        return notification_id is not None

    async def release_pending(
        self,
        *,
        idempotency_key: str,
        expected_attempts: int,
    ) -> bool:
        notification_id = await self._session.scalar(
            delete(NotificationModel)
            .where(
                NotificationModel.idempotency_key == idempotency_key,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.attempts == expected_attempts,
            )
            .returning(NotificationModel.id)
        )
        return notification_id is not None

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
            .values(
                status=NotificationStatus.FAILED,
                updated_at=reference_now,
            )
        )
