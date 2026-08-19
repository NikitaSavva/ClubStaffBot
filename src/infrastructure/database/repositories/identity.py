from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from application.identity.errors import UserAlreadyRegisteredError
from domain.identity import BotInvite, Role, SystemRoleCode, User
from infrastructure.database.models import (
    AuditLogModel,
    BotInviteModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.telegram_id == telegram_id)
        )
        if model is None:
            return None
        return User(
            id=model.id,
            telegram_id=model.telegram_id,
            username=model.username,
            first_name=model.first_name,
            last_name=model.last_name,
            is_active=model.is_active,
            registered_at=model.registered_at,
            last_seen_at=model.last_seen_at,
        )

    async def add(self, user: User) -> int:
        model = UserModel(
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            registered_at=user.registered_at,
            last_seen_at=user.last_seen_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise UserAlreadyRegisteredError from error
            raise
        return model.id


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: SystemRoleCode) -> Role | None:
        model = await self._session.scalar(
            select(RoleModel).where(RoleModel.code == code.value)
        )
        if model is None:
            return None
        return Role(
            id=model.id,
            code=SystemRoleCode(model.code),
            is_system=model.is_system,
            is_active=model.is_active,
        )

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> None:
        self._session.add(
            UserRoleModel(
                user_id=user_id,
                role_id=role_id,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=assigned_at,
            )
        )


class SqlAlchemyBotInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None:
        model = await self._session.scalar(
            select(BotInviteModel).where(
                BotInviteModel.token_hash == token_hash
            )
        )
        if model is None:
            return None
        return BotInvite(
            id=model.id,
            token_hash=model.token_hash,
            is_active=model.is_active,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
        )


class SqlAlchemyAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
    ) -> None:
        self._session.add(
            AuditLogModel(
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=None,
            )
        )
