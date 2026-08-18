from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container


@pytest.fixture
def settings() -> Settings:
    return Settings(
        postgres_host="database",
        postgres_port=5432,
        postgres_db="staff_bot",
        postgres_user="user",
        postgres_password="password",
        redis_host="cache",
        redis_port=6379,
        redis_db=0,
        telegram_bot_token="123456789:test-token",
        _env_file=None,
    )


async def test_container_resolves_app_and_request_dependencies(
    settings: Settings,
) -> None:
    with (
        patch.object(AsyncEngine, "dispose", new_callable=AsyncMock) as dispose,
        patch.object(AsyncSession, "close", new_callable=AsyncMock) as close_session,
        patch.object(Redis, "aclose", new_callable=AsyncMock) as close_redis,
    ):
        container = create_container(settings)
        resolved_settings = await container.get(Settings)
        engine = await container.get(AsyncEngine)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        redis = await container.get(Redis)

        async with container() as request_container:
            first_session = await request_container.get(AsyncSession)
            second_session = await request_container.get(AsyncSession)
            assert first_session is second_session

        await container.close()

        assert resolved_settings is settings
        assert session_factory.kw["bind"] is engine
        assert redis.connection_pool.connection_kwargs["host"] == "cache"
        close_session.assert_awaited_once()
        dispose.assert_awaited_once()
        close_redis.assert_awaited_once()
