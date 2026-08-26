from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.subscriptions import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from infrastructure.database.integrity_errors import translate_integrity_error
from infrastructure.database.models import (
    SubscriptionModel,
    SubscriptionPlanModel,
)


class SqlAlchemySubscriptionPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        subscription_plan_id: int,
    ) -> SubscriptionPlan | None:
        model = await self._session.get(
            SubscriptionPlanModel,
            subscription_plan_id,
        )
        return _to_subscription_plan(model)


class SqlAlchemySubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_by_athlete(
        self,
        athlete_id: int,
    ) -> Subscription | None:
        model = await self._session.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.athlete_id == athlete_id,
                SubscriptionModel.status == SubscriptionStatus.ACTIVE,
            )
        )
        return _to_subscription(model)

    async def mark_expired(self, subscription_id: int) -> bool:
        expired_id = await self._session.scalar(
            update(SubscriptionModel)
            .where(
                SubscriptionModel.id == subscription_id,
                SubscriptionModel.status == SubscriptionStatus.ACTIVE,
            )
            .values(status=SubscriptionStatus.EXPIRED)
            .returning(SubscriptionModel.id)
        )
        return expired_id is not None

    async def add(self, subscription: Subscription) -> int:
        model = SubscriptionModel(
            athlete_id=subscription.athlete_id,
            group_id=subscription.group_id,
            plan_id=subscription.plan_id,
            activated_by_user_id=subscription.activated_by_user_id,
            activated_at=subscription.activated_at,
            starts_at=subscription.starts_at,
            expires_at=subscription.expires_at,
            activation_price=subscription.activation_price,
            remaining_visits=subscription.remaining_visits,
            status=subscription.status,
        )
        self._session.add(model)
        try:
            # The generated id and partial unique constraint materialize here.
            await self._session.flush()
        except IntegrityError as error:
            translated = translate_integrity_error(error)
            if translated is error:
                raise
            raise translated from error
        return model.id


def _to_subscription_plan(
    model: SubscriptionPlanModel | None,
) -> SubscriptionPlan | None:
    if model is None:
        return None
    return SubscriptionPlan(
        id=model.id,
        code=model.code,
        name=model.name,
        visit_limit=model.visit_limit,
        duration_months=model.duration_months,
        price=model.price,
        is_unlimited=model.is_unlimited,
        access_scope=model.access_scope,
        required_group_type=model.required_group_type,
        is_active=model.is_active,
    )


def _to_subscription(
    model: SubscriptionModel | None,
) -> Subscription | None:
    if model is None:
        return None
    return Subscription(
        id=model.id,
        athlete_id=model.athlete_id,
        group_id=model.group_id,
        plan_id=model.plan_id,
        activated_by_user_id=model.activated_by_user_id,
        activated_at=model.activated_at,
        starts_at=model.starts_at,
        expires_at=model.expires_at,
        activation_price=model.activation_price,
        remaining_visits=model.remaining_visits,
        status=model.status,
    )
