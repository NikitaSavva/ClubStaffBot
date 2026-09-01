from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

WEBAPP_DIRECTORY = Path(__file__).parent.parent / "webapp"

router = APIRouter(include_in_schema=False)


@router.api_route("/webapp/scanner", methods=["GET", "HEAD"])
async def scanner_webapp() -> FileResponse:
    return FileResponse(
        WEBAPP_DIRECTORY / "scanner.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )
