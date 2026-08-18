from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from bootstrap.config import Settings
from infrastructure.redis.client import create_redis_client


class RedisProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_redis(
        self,
        settings: Settings,
    ) -> AsyncIterator[Redis]:
        client = create_redis_client(settings.redis_url)
        try:
            yield client
        finally:
            await client.aclose()
