from enum import StrEnum

from domain.attendance import AttendanceSource as AttendanceSource
from domain.attendance import AttendanceStatus as AttendanceStatus
from domain.club import TrainingGroupType as TrainingGroupType
from domain.club import TrainingSessionStatus as TrainingSessionStatus
from domain.subscriptions import (
    SubscriptionAccessScope as SubscriptionAccessScope,
)
from domain.subscriptions import SubscriptionStatus as SubscriptionStatus


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
