from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.models.base import Base
from infrastructure.database.models.enums import NotificationStatus
from infrastructure.database.models.mixins import TimestampMixin


class NotificationModel(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    training_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_sessions.id")
    )
    type: Mapped[str] = mapped_column(String)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status")
    )
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    attempts: Mapped[int] = mapped_column(Integer)
