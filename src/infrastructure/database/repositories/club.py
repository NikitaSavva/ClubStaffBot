from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.club import TrainingGroup
from infrastructure.database.models import TrainingGroupModel


class SqlAlchemyTrainingGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        training_group_id: int,
    ) -> TrainingGroup | None:
        model = await self._session.get(TrainingGroupModel, training_group_id)
        return _to_training_group(model)

    async def get_by_id_for_update(
        self,
        training_group_id: int,
    ) -> TrainingGroup | None:
        model = await self._session.scalar(
            select(TrainingGroupModel)
            .where(TrainingGroupModel.id == training_group_id)
            .with_for_update()
        )
        return _to_training_group(model)

    async def assign_trainer(
        self,
        *,
        training_group_id: int,
        trainer_user_id: int,
    ) -> bool:
        assigned_group_id = await self._session.scalar(
            update(TrainingGroupModel)
            .where(
                TrainingGroupModel.id == training_group_id,
                TrainingGroupModel.trainer_id.is_(None),
            )
            .values(trainer_id=trainer_user_id)
            .returning(TrainingGroupModel.id)
        )
        return assigned_group_id is not None


def _to_training_group(
    model: TrainingGroupModel | None,
) -> TrainingGroup | None:
    if model is None:
        return None
    return TrainingGroup(
        id=model.id,
        trainer_id=model.trainer_id,
        group_type=model.group_type,
    )
