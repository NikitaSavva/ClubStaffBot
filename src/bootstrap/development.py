from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.identity.ports import InviteTokenHasher
from infrastructure.database.development_invites import (
    create_development_invite as persist_development_invite,
)


async def create_development_invite(container: AsyncContainer) -> str:
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    token_hasher = await container.get(InviteTokenHasher)
    return await persist_development_invite(session_factory, token_hasher)
