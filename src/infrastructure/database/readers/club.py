from dataclasses import dataclass
from datetime import time

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.club.dto import (
    ScheduleRuleSummary,
    TrainerSummary,
    TrainingGroupSummary,
)
from domain.club import TrainingGroupType
from infrastructure.database.models import (
    GroupNameModel,
    ScheduleRuleModel,
    SportDirectionModel,
    TrainingGroupModel,
    UserModel,
)


@dataclass(slots=True)
class _TrainingGroupRow:
    training_group_id: int
    direction_name: str
    group_name: str
    group_type: TrainingGroupType
    trainer: TrainerSummary | None
    schedule_rules: list[ScheduleRuleSummary]


class SqlAlchemyTrainingGroupReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> tuple[TrainingGroupSummary, ...]:
        rows = (
            await self._session.execute(
                select(
                    TrainingGroupModel.id,
                    SportDirectionModel.name,
                    GroupNameModel.name,
                    TrainingGroupModel.group_type,
                    ScheduleRuleModel.weekday,
                    ScheduleRuleModel.start_time,
                    ScheduleRuleModel.end_time,
                    UserModel.id,
                    UserModel.first_name,
                    UserModel.last_name,
                    UserModel.username,
                )
                .join(
                    SportDirectionModel,
                    SportDirectionModel.id == TrainingGroupModel.direction_id,
                )
                .join(
                    GroupNameModel,
                    GroupNameModel.id == TrainingGroupModel.name_id,
                )
                .outerjoin(
                    ScheduleRuleModel,
                    and_(
                        ScheduleRuleModel.group_id == TrainingGroupModel.id,
                        ScheduleRuleModel.is_active.is_(True),
                    ),
                )
                .outerjoin(
                    UserModel,
                    UserModel.id == TrainingGroupModel.trainer_id,
                )
                .order_by(
                    SportDirectionModel.name.asc(),
                    GroupNameModel.name.asc(),
                    TrainingGroupModel.id.asc(),
                    ScheduleRuleModel.weekday.asc().nulls_last(),
                    ScheduleRuleModel.start_time.asc().nulls_last(),
                )
            )
        ).all()

        groups: dict[int, _TrainingGroupRow] = {}
        for row in rows:
            trainer = (
                TrainerSummary(
                    user_id=row[7],
                    first_name=row[8],
                    last_name=row[9],
                    username=row[10],
                )
                if row[7] is not None
                else None
            )
            group = groups.setdefault(
                row[0],
                _TrainingGroupRow(
                    training_group_id=row[0],
                    direction_name=row[1],
                    group_name=row[2],
                    group_type=TrainingGroupType(row[3]),
                    trainer=trainer,
                    schedule_rules=[],
                ),
            )
            weekday: int | None = row[4]
            start_time: time | None = row[5]
            end_time: time | None = row[6]
            if (
                weekday is not None
                and start_time is not None
                and end_time is not None
            ):
                group.schedule_rules.append(
                    ScheduleRuleSummary(
                        weekday=weekday,
                        start_time=start_time,
                        end_time=end_time,
                    )
                )

        return tuple(
            TrainingGroupSummary(
                training_group_id=group.training_group_id,
                direction_name=group.direction_name,
                group_name=group.group_name,
                group_type=group.group_type,
                schedule_rules=tuple(group.schedule_rules),
                trainer=group.trainer,
            )
            for group in groups.values()
        )
