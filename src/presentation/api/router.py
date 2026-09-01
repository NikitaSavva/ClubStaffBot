from typing import Literal, TypedDict

from fastapi import APIRouter

from presentation.api.scanner import router as scanner_router
from presentation.api.webapp import router as webapp_router

router = APIRouter()
router.include_router(scanner_router)
router.include_router(webapp_router)


class HealthResponse(TypedDict):
    status: Literal["ok"]


@router.get("/health")
async def health() -> HealthResponse:
    return {"status": "ok"}
