from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.models.base import Base
from infrastructure.database.models.enums import TrainingSessionStatus
from infrastructure.database.models.mixins import TimestampMixin


class SportDirectionModel(TimestampMixin, Base):
    __tablename__ = "sport_directions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean)


class TrainingGroupModel(TimestampMixin, Base):
    __tablename__ = "training_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction_id: Mapped[int] = mapped_column(ForeignKey("sport_directions.id"))
    trainer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean)


class ScheduleRuleModel(TimestampMixin, Base):
    __tablename__ = "schedule_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("training_groups.id"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean)


class TrainingSessionModel(TimestampMixin, Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        UniqueConstraint("schedule_rule_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_rules.id")
    )
    group_id: Mapped[int] = mapped_column(ForeignKey("training_groups.id"))
    trainer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[TrainingSessionStatus] = mapped_column(
        Enum(TrainingSessionStatus, name="training_session_status")
    )
    is_overridden: Mapped[bool] = mapped_column(Boolean)
