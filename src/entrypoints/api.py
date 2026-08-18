from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from bootstrap.config import Settings
from bootstrap.container import create_container
from presentation.api.router import router


def create_app(settings: Settings | None = None) -> FastAPI:
    container = create_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title="Staff Bot API", lifespan=lifespan)
    app.include_router(router)
    setup_dishka(container, app)
    return app
