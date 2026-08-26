from enum import StrEnum


class SubscriptionAccessScope(StrEnum):
    SPECIFIC_GROUP = "SPECIFIC_GROUP"
    ALL_REGULAR_GROUPS = "ALL_REGULAR_GROUPS"
