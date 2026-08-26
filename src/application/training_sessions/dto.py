from dataclasses import dataclass
from datetime import date, datetime, time

from domain.club import TrainingSessionStatus


@dataclass(frozen=True, slots=True)
class GenerationWindow:
    date_from: date
    date_to: date


@dataclass(frozen=True, slots=True)
class ScheduleRuleForGeneration:
    schedule_rule_id: int
    training_group_id: int
    trainer_id: int | None
    direction_name: str
    group_name: str
    weekday: int
    start_time: time
    end_time: time
    valid_from: date | None
    valid_until: date | None
    is_active: bool


@dataclass(frozen=True, slots=True, order=True)
class ScheduleRuleDescriptor:
    weekday: int
    start_time: time
    end_time: time


@dataclass(frozen=True, slots=True)
class TrainingGroupWithoutTrainer:
    training_group_id: int
    direction_name: str
    group_name: str
    schedule: tuple[ScheduleRuleDescriptor, ...]


@dataclass(frozen=True, slots=True)
class NewTrainingSession:
    schedule_rule_id: int
    training_group_id: int
    trainer_id: int
    starts_at: datetime
    ends_at: datetime
    status: TrainingSessionStatus
    is_overridden: bool


@dataclass(frozen=True, slots=True)
class GenerateTrainingSessionsResult:
    date_from: date
    date_to: date
    created_count: int
    skipped_count: int
