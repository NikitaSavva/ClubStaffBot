from dataclasses import dataclass
from datetime import time

from domain.club import TrainingGroupType


@dataclass(frozen=True, slots=True)
class TrainerSummary:
    user_id: int
    first_name: str
    last_name: str
    username: str | None

    @property
    def display_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
        )


@dataclass(frozen=True, slots=True)
class ScheduleRuleSummary:
    weekday: int
    start_time: time
    end_time: time


@dataclass(frozen=True, slots=True)
class TrainingGroupSummary:
    training_group_id: int
    direction_name: str
    group_name: str
    group_type: TrainingGroupType
    schedule_rules: tuple[ScheduleRuleSummary, ...]
    trainer: TrainerSummary | None


@dataclass(frozen=True, slots=True)
class AssignTrainingGroupTrainerResult:
    training_group_id: int
    trainer_user_id: int
