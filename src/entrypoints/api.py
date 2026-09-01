from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bootstrap.config import Settings
from bootstrap.container import create_container
from presentation.api.router import router
from presentation.api.webapp import WEBAPP_DIRECTORY


def create_app(settings: Settings | None = None) -> FastAPI:
    container = create_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title="Staff Bot API", lifespan=lifespan)
    app.mount(
        "/webapp/static",
        StaticFiles(
            directory=WEBAPP_DIRECTORY,
            html=False,
            follow_symlink=False,
        ),
        name="webapp-static",
    )
    app.include_router(router)
    setup_dishka(container, app)
    return app
