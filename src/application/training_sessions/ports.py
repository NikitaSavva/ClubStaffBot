from datetime import date
from typing import Protocol

from application.training_sessions.dto import (
    NewTrainingSession,
    ScheduleRuleForGeneration,
)


class ScheduleRuleRepository(Protocol):
    async def list_for_generation(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> tuple[ScheduleRuleForGeneration, ...]: ...


class TrainingSessionRepository(Protocol):
    async def add_missing(
        self,
        training_sessions: tuple[NewTrainingSession, ...],
    ) -> int: ...
