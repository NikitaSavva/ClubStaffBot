from datetime import datetime
from typing import Protocol

from application.attendance.dto import AttendanceSessionCandidate
from domain.attendance import Attendance


class AttendanceRepository(Protocol):
    async def exists(
        self,
        *,
        training_session_id: int,
        athlete_id: int,
    ) -> bool: ...

    async def add(self, attendance: Attendance) -> int: ...


class AttendanceSessionRepository(Protocol):
    async def list_by_group_for_update(
        self,
        *,
        training_group_id: int,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]: ...

    async def list_regular(
        self,
        *,
        starts_at_from: datetime,
        starts_at_to: datetime,
    ) -> tuple[AttendanceSessionCandidate, ...]: ...

    async def get_by_id_for_update(
        self,
        training_session_id: int,
    ) -> AttendanceSessionCandidate | None: ...
