from datetime import datetime, timedelta

from sqlalchemy import and_, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.trainer_notifications import (
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
from infrastructure.database.notification_delivery import (
    SqlAlchemyNotificationDeliveryRepository,
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


SqlAlchemyTrainerNotificationDeliveryRepository = (
    SqlAlchemyNotificationDeliveryRepository
)
