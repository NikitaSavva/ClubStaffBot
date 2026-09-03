from datetime import datetime, timedelta

from sqlalchemy import String, and_, cast, exists, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.athlete_notifications import (
    AthleteNotificationCandidate,
    AthleteNotificationReader,
    AthleteNotificationRecipient,
    AthleteNotificationSession,
)
from domain.club import TrainingSessionStatus
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.models import (
    AthleteModel,
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

NOTIFICATION_TYPE = "ATHLETE_SESSION_MINUS_2H"


class SqlAlchemyAthleteNotificationReader(AthleteNotificationReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_due_candidates(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        grace_window_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[AthleteNotificationCandidate, ...]:
        notify_before = timedelta(seconds=notify_before_seconds)
        grace_window = timedelta(seconds=grace_window_seconds)
        logical_key = (
            literal(f"{NOTIFICATION_TYPE}:")
            + cast(TrainingSessionModel.id, String)
            + literal(":")
            + cast(AthleteModel.id, String)
        )
        blocking_notification = exists(
            select(NotificationModel.id).where(
                NotificationModel.idempotency_key == logical_key,
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
        effective_subscription = and_(
            SubscriptionModel.status == SubscriptionStatus.ACTIVE,
            SubscriptionModel.starts_at <= reference_now,
            reference_now < SubscriptionModel.expires_at,
            or_(
                SubscriptionModel.remaining_visits.is_(None),
                SubscriptionModel.remaining_visits > 0,
            ),
            SubscriptionPlanModel.access_scope
            == SubscriptionAccessScope.SPECIFIC_GROUP,
            SubscriptionModel.group_id == TrainingSessionModel.group_id,
        )
        due_candidates = (
            select(
                TrainingSessionModel.id.label("training_session_id"),
                AthleteModel.id.label("athlete_id"),
                TrainingSessionModel.starts_at.label("starts_at"),
            )
            .select_from(TrainingSessionModel)
            .join(
                SubscriptionModel,
                SubscriptionModel.group_id == TrainingSessionModel.group_id,
            )
            .join(
                SubscriptionPlanModel,
                SubscriptionPlanModel.id == SubscriptionModel.plan_id,
            )
            .join(AthleteModel, AthleteModel.id == SubscriptionModel.athlete_id)
            .join(UserModel, UserModel.id == AthleteModel.user_id)
            .where(
                TrainingSessionModel.starts_at
                <= reference_now + notify_before,
                TrainingSessionModel.starts_at
                > reference_now + notify_before - grace_window,
                TrainingSessionModel.status != TrainingSessionStatus.CANCELLED,
                effective_subscription,
                ~blocking_notification,
            )
            .distinct()
        )

        stale_key = (
            literal(f"{NOTIFICATION_TYPE}:")
            + cast(NotificationModel.training_session_id, String)
            + literal(":")
            + cast(AthleteModel.id, String)
        )
        stale_candidates = (
            select(
                TrainingSessionModel.id.label("training_session_id"),
                AthleteModel.id.label("athlete_id"),
                TrainingSessionModel.starts_at.label("starts_at"),
            )
            .select_from(NotificationModel)
            .join(
                TrainingSessionModel,
                TrainingSessionModel.id == NotificationModel.training_session_id,
            )
            .join(
                AthleteModel,
                AthleteModel.user_id == NotificationModel.recipient_user_id,
            )
            .where(
                NotificationModel.type == NOTIFICATION_TYPE,
                NotificationModel.status == NotificationStatus.PENDING,
                NotificationModel.updated_at <= stale_pending_before,
                NotificationModel.idempotency_key == stale_key,
            )
        )
        candidates = due_candidates.union(stale_candidates).subquery()
        rows = await self._session.execute(
            select(
                candidates.c.training_session_id,
                candidates.c.athlete_id,
            ).order_by(
                candidates.c.starts_at,
                candidates.c.training_session_id,
                candidates.c.athlete_id,
            )
        )
        return tuple(
            AthleteNotificationCandidate(
                training_session_id=row.training_session_id,
                athlete_id=row.athlete_id,
            )
            for row in rows
        )

    async def get_session(
        self,
        training_session_id: int,
    ) -> AthleteNotificationSession | None:
        row = (
            await self._session.execute(
                select(
                    TrainingSessionModel.id,
                    TrainingSessionModel.group_id,
                    TrainingSessionModel.starts_at,
                    TrainingSessionModel.ends_at,
                    TrainingSessionModel.status,
                    SportDirectionModel.name.label("sport_direction_name"),
                    GroupNameModel.name.label("group_name"),
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
                .where(TrainingSessionModel.id == training_session_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return AthleteNotificationSession(
            id=row.id,
            group_id=row.group_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            sport_direction_name=row.sport_direction_name,
            group_name=row.group_name,
        )

    async def get_eligible_recipient(
        self,
        *,
        athlete_id: int,
        training_group_id: int,
        reference_now: datetime,
    ) -> AthleteNotificationRecipient | None:
        row = (
            await self._session.execute(
                select(
                    AthleteModel.id.label("athlete_id"),
                    UserModel.id.label("user_id"),
                    UserModel.telegram_id.label("telegram_id"),
                )
                .select_from(AthleteModel)
                .join(UserModel, UserModel.id == AthleteModel.user_id)
                .join(
                    SubscriptionModel,
                    SubscriptionModel.athlete_id == AthleteModel.id,
                )
                .join(
                    SubscriptionPlanModel,
                    SubscriptionPlanModel.id == SubscriptionModel.plan_id,
                )
                .where(
                    AthleteModel.id == athlete_id,
                    SubscriptionModel.status == SubscriptionStatus.ACTIVE,
                    SubscriptionModel.starts_at <= reference_now,
                    reference_now < SubscriptionModel.expires_at,
                    or_(
                        SubscriptionModel.remaining_visits.is_(None),
                        SubscriptionModel.remaining_visits > 0,
                    ),
                    SubscriptionPlanModel.access_scope
                    == SubscriptionAccessScope.SPECIFIC_GROUP,
                    SubscriptionModel.group_id == training_group_id,
                )
                .distinct()
            )
        ).one_or_none()
        if row is None:
            return None
        return AthleteNotificationRecipient(
            athlete_id=row.athlete_id,
            user_id=row.user_id,
            telegram_id=row.telegram_id,
        )
