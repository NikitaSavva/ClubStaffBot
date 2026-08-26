from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from application.training_sessions import (
    NewTrainingSession,
    ScheduleRuleForGeneration,
)
from infrastructure.database.models import (
    GroupNameModel,
    ScheduleRuleModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
)


class SqlAlchemyScheduleRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_generation(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> tuple[ScheduleRuleForGeneration, ...]:
        rows = (
            await self._session.execute(
                select(
                    ScheduleRuleModel.id,
                    TrainingGroupModel.id,
                    TrainingGroupModel.trainer_id,
                    SportDirectionModel.name,
                    GroupNameModel.name,
                    ScheduleRuleModel.weekday,
                    ScheduleRuleModel.start_time,
                    ScheduleRuleModel.end_time,
                    ScheduleRuleModel.valid_from,
                    ScheduleRuleModel.valid_until,
                    ScheduleRuleModel.is_active,
                )
                .join(
                    TrainingGroupModel,
                    TrainingGroupModel.id == ScheduleRuleModel.group_id,
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
                    ScheduleRuleModel.is_active.is_(True),
                    TrainingGroupModel.is_active.is_(True),
                    or_(
                        ScheduleRuleModel.valid_from.is_(None),
                        ScheduleRuleModel.valid_from <= date_to,
                    ),
                    or_(
                        ScheduleRuleModel.valid_until.is_(None),
                        ScheduleRuleModel.valid_until >= date_from,
                    ),
                )
                .order_by(
                    SportDirectionModel.name,
                    GroupNameModel.name,
                    TrainingGroupModel.id,
                    ScheduleRuleModel.weekday,
                    ScheduleRuleModel.start_time,
                    ScheduleRuleModel.id,
                )
            )
        ).all()
        return tuple(
            ScheduleRuleForGeneration(
                schedule_rule_id=row[0],
                training_group_id=row[1],
                trainer_id=row[2],
                direction_name=row[3],
                group_name=row[4],
                weekday=row[5],
                start_time=row[6],
                end_time=row[7],
                valid_from=row[8],
                valid_until=row[9],
                is_active=row[10],
            )
            for row in rows
        )


class SqlAlchemyTrainingSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_missing(
        self,
        training_sessions: tuple[NewTrainingSession, ...],
    ) -> int:
        if not training_sessions:
            return 0

        statement = (
            insert(TrainingSessionModel)
            .values(
                [
                    {
                        "schedule_rule_id": training_session.schedule_rule_id,
                        "group_id": training_session.training_group_id,
                        "trainer_id": training_session.trainer_id,
                        "starts_at": training_session.starts_at,
                        "ends_at": training_session.ends_at,
                        "status": training_session.status,
                        "is_overridden": training_session.is_overridden,
                    }
                    for training_session in training_sessions
                ]
            )
            .on_conflict_do_nothing(
                index_elements=("schedule_rule_id", "starts_at"),
            )
            .returning(TrainingSessionModel.id)
        )
        created_ids = (await self._session.scalars(statement)).all()
        return len(created_ids)
