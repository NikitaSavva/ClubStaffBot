from dataclasses import dataclass
from enum import StrEnum


class TrainingGroupType(StrEnum):
    REGULAR = "REGULAR"
    MINI = "MINI"


class TrainingSessionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class TrainingGroup:
    id: int
    trainer_id: int | None
    group_type: TrainingGroupType = TrainingGroupType.REGULAR
