from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.models.base import Base
from infrastructure.database.models.enums import (
    SubscriptionAccessScope,
    SubscriptionStatus,
    TrainingGroupType,
)
from infrastructure.database.models.mixins import TimestampMixin


class SubscriptionPlanModel(TimestampMixin, Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    visit_limit: Mapped[int | None] = mapped_column(Integer)
    duration_months: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric)
    is_unlimited: Mapped[bool] = mapped_column(Boolean)
    access_scope: Mapped[SubscriptionAccessScope] = mapped_column(
        Enum(SubscriptionAccessScope, name="subscription_access_scope")
    )
    required_group_type: Mapped[TrainingGroupType | None] = mapped_column(
        Enum(TrainingGroupType, name="training_group_type")
    )
    is_active: Mapped[bool] = mapped_column(Boolean)


class SubscriptionModel(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "remaining_visits IS NULL OR remaining_visits >= 0",
            name="remaining_visits_non_negative",
        ),
        Index(
            "uq_subscriptions_active_athlete_id",
            "athlete_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_groups.id")
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"))
    activated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activation_price: Mapped[Decimal] = mapped_column(Numeric)
    remaining_visits: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status")
    )
