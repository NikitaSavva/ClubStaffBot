from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer

from infrastructure.database.session import create_engine, create_session_factory

PROJECT_ROOT = Path(__file__).parents[3]


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(
        "postgres:16-alpine",
        driver="asyncpg",
    ) as postgres:
        url = postgres.get_connection_url()
        config = alembic_config(url)
        command.upgrade(config, "head")
        yield url
        command.downgrade(config, "base")


@pytest.fixture
async def db_session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()
