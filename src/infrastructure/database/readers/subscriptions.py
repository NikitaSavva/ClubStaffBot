from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.subscriptions import SubscriptionPlanSummary
from infrastructure.database.models import SubscriptionPlanModel


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
