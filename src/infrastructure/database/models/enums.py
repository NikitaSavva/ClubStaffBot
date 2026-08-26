from enum import StrEnum

from domain.club import TrainingGroupType as TrainingGroupType
from domain.club import TrainingSessionStatus as TrainingSessionStatus
from domain.subscriptions import (
    SubscriptionAccessScope as SubscriptionAccessScope,
)
from domain.subscriptions import SubscriptionStatus as SubscriptionStatus


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
