import secrets

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.identity.ports import InviteTokenHasher
from domain.identity import BotInvitePurpose
from infrastructure.database.models import BotInviteModel


async def create_development_invite(
    session_factory: async_sessionmaker[AsyncSession],
    token_hasher: InviteTokenHasher,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = token_hasher.hash(raw_token)

    async with session_factory.begin() as session:
        session.add(
            BotInviteModel(
                token_hash=token_hash,
                purpose=BotInvitePurpose.REGISTRATION,
                athlete_id=None,
                is_active=True,
                expires_at=None,
                revoked_at=None,
                consumed_at=None,
            )
        )

    return raw_token
