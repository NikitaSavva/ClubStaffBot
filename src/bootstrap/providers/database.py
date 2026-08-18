from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from infrastructure.database.session import create_engine, create_session_factory


class DatabaseProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_engine(
        self,
        settings: Settings,
    ) -> AsyncIterator[AsyncEngine]:
        engine = create_engine(settings.database_url)
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def provide_session_factory(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return create_session_factory(engine)

    @provide(scope=Scope.REQUEST)
    async def provide_session(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
