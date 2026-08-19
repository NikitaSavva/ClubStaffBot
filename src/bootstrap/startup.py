from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.system_roles import ensure_system_roles


async def bootstrap_system_roles(container: AsyncContainer) -> None:
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    await ensure_system_roles(session_factory)
