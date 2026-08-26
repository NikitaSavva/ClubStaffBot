from enum import StrEnum

from domain.club import TrainingGroupType as TrainingGroupType
from domain.club import TrainingSessionStatus as TrainingSessionStatus
from domain.subscriptions import (
    SubscriptionAccessScope as SubscriptionAccessScope,
)


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AttendanceSource(StrEnum):
    QR = "QR"
    MANUAL = "MANUAL"


class AttendanceStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
