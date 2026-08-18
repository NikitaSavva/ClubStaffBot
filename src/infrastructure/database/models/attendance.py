from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.models.base import Base
from infrastructure.database.models.enums import AttendanceSource, AttendanceStatus
from infrastructure.database.models.mixins import TimestampMixin


class AttendanceModel(TimestampMixin, Base):
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("training_session_id", "athlete_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id")
    )
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    confirmed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[AttendanceSource] = mapped_column(
        Enum(AttendanceSource, name="attendance_source")
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status")
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
