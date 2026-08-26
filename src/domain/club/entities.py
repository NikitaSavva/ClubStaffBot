from dataclasses import dataclass
from enum import StrEnum


class TrainingGroupType(StrEnum):
    REGULAR = "REGULAR"
    MINI = "MINI"


@dataclass(frozen=True, slots=True)
class TrainingGroup:
    id: int
    trainer_id: int | None
