from typing import Literal, TypedDict

from fastapi import APIRouter

router = APIRouter()


class HealthResponse(TypedDict):
    status: Literal["ok"]


@router.get("/health")
async def health() -> HealthResponse:
    return {"status": "ok"}
