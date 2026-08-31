from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.training_sessions import (
    CurrentWeekScheduleFilters,
    ScheduleSessionItem,
)
from infrastructure.database.models import (
    GroupNameModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
)


class SqlAlchemyCurrentWeekScheduleReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        filters: CurrentWeekScheduleFilters,
    ) -> tuple[ScheduleSessionItem, ...]:
        statement = (
            select(
                TrainingSessionModel.id,
                TrainingSessionModel.group_id.label("training_group_id"),
                TrainingSessionModel.starts_at,
                TrainingSessionModel.ends_at,
                TrainingSessionModel.status,
                SportDirectionModel.name.label("sport_direction_name"),
                GroupNameModel.name.label("group_name"),
            )
            .select_from(TrainingSessionModel)
            .join(
                TrainingGroupModel,
                TrainingGroupModel.id == TrainingSessionModel.group_id,
            )
            .join(
                SportDirectionModel,
                SportDirectionModel.id == TrainingGroupModel.direction_id,
            )
            .join(
                GroupNameModel,
                GroupNameModel.id == TrainingGroupModel.name_id,
            )
            .where(
                TrainingSessionModel.starts_at >= filters.week_start,
                TrainingSessionModel.starts_at < filters.week_end,
            )
        )
        if filters.training_group_id is not None:
            statement = statement.where(
                TrainingSessionModel.group_id == filters.training_group_id
            )
        if filters.trainer_id is not None:
            statement = statement.where(
                TrainingSessionModel.trainer_id == filters.trainer_id
            )
        if filters.group_type is not None:
            statement = statement.where(
                TrainingGroupModel.group_type == filters.group_type
            )

        rows = (
            await self._session.execute(
                statement.order_by(
                    TrainingSessionModel.starts_at.asc(),
                    TrainingSessionModel.id.asc(),
                )
            )
        ).all()
        return tuple(
            ScheduleSessionItem(
                id=row.id,
                training_group_id=row.training_group_id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                status=row.status,
                sport_direction_name=row.sport_direction_name,
                group_name=row.group_name,
            )
            for row in rows
        )
