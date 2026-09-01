from datetime import datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from application.attendance import (
    AttendanceRepository,
    AttendanceSessionCandidate,
    AttendanceSessionRepository,
)
from domain.attendance import Attendance
from domain.club import TrainingGroupType
from infrastructure.database.integrity_errors import translate_integrity_error
from infrastructure.database.models import (
    AttendanceModel,
    GroupNameModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
)


class SqlAlchemyAttendanceRepository(AttendanceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(
        self,
        *,
        training_session_id: int,
        athlete_id: int,
    ) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        AttendanceModel.training_session_id
                        == training_session_id,
                        AttendanceModel.athlete_id == athlete_id,
                    )
                )
            )
        )

    async def add(self, attendance: Attendance) -> int:
        model = AttendanceModel(
            training_session_id=attendance.training_session_id,
            athlete_id=attendance.athlete_id,
            subscription_id=attendance.subscription_id,
            confirmed_by_user_id=attendance.confirmed_by_user_id,
            source=attendance.source,
            status=attendance.status,
            confirmed_at=attendance.confirmed_at,
        )
        self._session.add(model)
        try:
            # Flush before changing Subscription balance. The DB uniqueness
            # constraint remains the final duplicate protection.
            await self._session.flush()
        except IntegrityError as error:
            translated = translate_integrity_error(error)
            if translated is error:
                raise
            raise translated from error
        return model.id


class SqlAlchemyAttendanceSessionRepository(AttendanceSessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_group_for_update(
        self,
        *,
        training_group_id: int,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]:
        statement = _candidate_statement().where(
            TrainingSessionModel.group_id == training_group_id,
            TrainingSessionModel.starts_at >= starts_at_from,
            TrainingSessionModel.starts_at < starts_at_to,
        )
        rows = (
            await self._session.execute(
                statement.order_by(
                    TrainingSessionModel.starts_at.asc(),
                    TrainingSessionModel.id.asc(),
                ).with_for_update(of=TrainingSessionModel)
            )
        ).all()
        return tuple(_to_candidate(row) for row in rows)

    async def list_regular(
        self,
        *,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]:
        rows = (
            await self._session.execute(
                _candidate_statement()
                .where(
                    TrainingSessionModel.starts_at >= starts_at_from,
                    TrainingSessionModel.starts_at < starts_at_to,
                    TrainingGroupModel.group_type
                    == TrainingGroupType.REGULAR,
                )
                .order_by(
                    TrainingSessionModel.starts_at.asc(),
                    TrainingSessionModel.id.asc(),
                )
            )
        ).all()
        return tuple(_to_candidate(row) for row in rows)

    async def get_by_id_for_update(
        self,
        training_session_id: int,
    ) -> AttendanceSessionCandidate | None:
        row = (
            await self._session.execute(
                _candidate_statement()
                .where(TrainingSessionModel.id == training_session_id)
                .with_for_update(of=TrainingSessionModel)
            )
        ).one_or_none()
        return _to_candidate(row) if row is not None else None


def _candidate_statement() -> Any:
    return (
        select(
            TrainingSessionModel.id,
            TrainingSessionModel.group_id.label("training_group_id"),
            TrainingSessionModel.starts_at,
            TrainingSessionModel.ends_at,
            TrainingSessionModel.status,
            TrainingGroupModel.group_type,
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
    )


def _to_candidate(row: Any) -> AttendanceSessionCandidate:
    return AttendanceSessionCandidate(
        id=row.id,
        training_group_id=row.training_group_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        status=row.status,
        group_type=row.group_type,
        sport_direction_name=row.sport_direction_name,
        group_name=row.group_name,
    )
