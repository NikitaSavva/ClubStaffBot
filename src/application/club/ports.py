from typing import Protocol

from application.club.dto import TrainingGroupSummary
from domain.club import TrainingGroup


class TrainingGroupRepository(Protocol):
    async def get_by_id_for_update(
        self,
        training_group_id: int,
    ) -> TrainingGroup | None: ...

    async def assign_trainer(
        self,
        *,
        training_group_id: int,
        trainer_user_id: int,
    ) -> bool: ...


class TrainingGroupReader(Protocol):
    async def list_all(self) -> tuple[TrainingGroupSummary, ...]: ...
