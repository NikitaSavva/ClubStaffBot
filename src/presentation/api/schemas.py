from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class ScannerResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=2048)


class ScannerResolveResponse(BaseModel):
    full_name: str
    birth_date: date | None


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
