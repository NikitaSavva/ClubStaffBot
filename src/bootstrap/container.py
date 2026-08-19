from dishka import AsyncContainer, make_async_container

from bootstrap.config import Settings
from bootstrap.providers.application import ApplicationProvider
from bootstrap.providers.database import DatabaseProvider
from bootstrap.providers.infrastructure import InfrastructureProvider
from bootstrap.providers.redis import RedisProvider
from bootstrap.providers.repositories import RepositoryProvider
from bootstrap.providers.settings import SettingsProvider
from bootstrap.providers.telegram import TelegramProvider


def create_container(settings: Settings | None = None) -> AsyncContainer:
    # BaseSettings supplies these required values from the environment at runtime.
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    return make_async_container(
        SettingsProvider(resolved_settings),
        DatabaseProvider(),
        InfrastructureProvider(),
        RepositoryProvider(),
        ApplicationProvider(),
        RedisProvider(),
        TelegramProvider(),
    )
