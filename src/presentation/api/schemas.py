from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScannerAttendanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=2048)
    training_session_id: int | None = Field(default=None, gt=0)


class ScannerAttendanceAthleteResponse(BaseModel):
    full_name: str
    birth_date: date | None


class ScannerConfirmedSessionResponse(BaseModel):
    starts_at: datetime
    sport_direction_name: str
    group_name: str


class ScannerSelectableSessionResponse(BaseModel):
    training_session_id: int
    starts_at: datetime
    status: str
    sport_direction_name: str
    group_name: str
    selectable: bool


class ScannerAttendanceResponse(BaseModel):
    state: Literal["confirmed", "session_selection_required"]
    athlete: ScannerAttendanceAthleteResponse
    session: ScannerConfirmedSessionResponse | None = None
    sessions: tuple[ScannerSelectableSessionResponse, ...] = ()
    remaining_visits: int | None = None
    subscription_finished: bool = False


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
