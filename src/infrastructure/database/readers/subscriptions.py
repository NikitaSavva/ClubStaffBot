from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.subscriptions import (
    AthleteSubscriptionReadModel,
    MySubscriptionGroup,
    PersistedActiveSubscriptionReadModel,
    SubscriptionPlanSummary,
)
from domain.subscriptions import Subscription, SubscriptionStatus
from infrastructure.database.models import (
    AthleteModel,
    GroupNameModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
)


class SqlAlchemySubscriptionPlanReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> tuple[SubscriptionPlanSummary, ...]:
        models = await self._session.scalars(
            select(SubscriptionPlanModel)
            .where(SubscriptionPlanModel.is_active.is_(True))
            .order_by(SubscriptionPlanModel.id.asc())
        )
        return tuple(
            SubscriptionPlanSummary(
                subscription_plan_id=model.id,
                name=model.name,
                price=model.price,
                duration_months=model.duration_months,
                visit_limit=model.visit_limit,
                access_scope=model.access_scope,
                required_group_type=model.required_group_type,
            )
            for model in models
        )


class SqlAlchemyMySubscriptionReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(
        self,
        user_id: int,
    ) -> AthleteSubscriptionReadModel | None:
        row = (
            await self._session.execute(
                select(
                    AthleteModel.id.label("athlete_id"),
                    SubscriptionModel.id.label("subscription_id"),
                    SubscriptionModel.group_id,
                    SubscriptionModel.plan_id,
                    SubscriptionModel.activated_by_user_id,
                    SubscriptionModel.activated_at,
                    SubscriptionModel.starts_at,
                    SubscriptionModel.expires_at,
                    SubscriptionModel.activation_price,
                    SubscriptionModel.remaining_visits,
                    SubscriptionModel.status,
                    SubscriptionPlanModel.name.label("plan_name"),
                    SubscriptionPlanModel.is_unlimited,
                    SubscriptionPlanModel.access_scope,
                    TrainingGroupModel.id.label("training_group_id"),
                    SportDirectionModel.name.label("direction_name"),
                    GroupNameModel.name.label("group_name"),
                )
                .select_from(AthleteModel)
                .outerjoin(
                    SubscriptionModel,
                    and_(
                        SubscriptionModel.athlete_id == AthleteModel.id,
                        SubscriptionModel.status
                        == SubscriptionStatus.ACTIVE,
                    ),
                )
                .outerjoin(
                    SubscriptionPlanModel,
                    SubscriptionPlanModel.id == SubscriptionModel.plan_id,
                )
                .outerjoin(
                    TrainingGroupModel,
                    TrainingGroupModel.id == SubscriptionModel.group_id,
                )
                .outerjoin(
                    SportDirectionModel,
                    SportDirectionModel.id
                    == TrainingGroupModel.direction_id,
                )
                .outerjoin(
                    GroupNameModel,
                    GroupNameModel.id == TrainingGroupModel.name_id,
                )
                .where(AthleteModel.user_id == user_id)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.subscription_id is None:
            return AthleteSubscriptionReadModel(
                athlete_id=row.athlete_id,
                persisted_active=None,
            )
        if (
            row.plan_id is None
            or row.activated_by_user_id is None
            or row.activated_at is None
            or row.starts_at is None
            or row.expires_at is None
            or row.activation_price is None
            or row.status is None
            or row.plan_name is None
            or row.is_unlimited is None
            or row.access_scope is None
        ):
            raise RuntimeError("Persisted Subscription read model is incomplete")

        group = None
        if row.training_group_id is not None:
            if row.direction_name is None or row.group_name is None:
                raise RuntimeError(
                    "Persisted Subscription group read model is incomplete"
                )
            group = MySubscriptionGroup(
                training_group_id=row.training_group_id,
                direction_name=row.direction_name,
                group_name=row.group_name,
            )

        subscription = Subscription(
            id=row.subscription_id,
            athlete_id=row.athlete_id,
            group_id=row.group_id,
            plan_id=row.plan_id,
            activated_by_user_id=row.activated_by_user_id,
            activated_at=row.activated_at,
            starts_at=row.starts_at,
            expires_at=row.expires_at,
            activation_price=row.activation_price,
            remaining_visits=row.remaining_visits,
            status=row.status,
        )
        return AthleteSubscriptionReadModel(
            athlete_id=row.athlete_id,
            persisted_active=PersistedActiveSubscriptionReadModel(
                subscription=subscription,
                plan_name=row.plan_name,
                is_unlimited=row.is_unlimited,
                access_scope=row.access_scope,
                group=group,
            ),
        )
