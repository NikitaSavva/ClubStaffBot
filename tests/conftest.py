from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer

from bootstrap.config import Settings
from infrastructure.database.session import create_engine, create_session_factory

PROJECT_ROOT = Path(__file__).parents[1]


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


@pytest.fixture
def integration_settings(database_url: str) -> Settings:
    url = make_url(database_url)
    assert url.host is not None
    assert url.database is not None
    assert url.username is not None
    assert url.password is not None
    return Settings(
        postgres_host=url.host,
        postgres_port=url.port or 5432,
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=url.password,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        telegram_bot_token="123456789:test-token",
        admin_panel_banner_file_id="admin-banner-file-id",
        trainer_panel_banner_file_id="trainer-banner-file-id",
        athlete_panel_banner_file_id="athlete-banner-file-id",
        role_selector_banner_file_id="role-selector-banner-file-id",
        _env_file=None,
    )
