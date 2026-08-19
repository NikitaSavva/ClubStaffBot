from datetime import datetime
from typing import Protocol

from domain.identity import BotInvite, Role, SystemRoleCode, User


class UserRepository(Protocol):
    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def add(self, user: User) -> int: ...


class RoleRepository(Protocol):
    async def get_by_code(self, code: SystemRoleCode) -> Role | None: ...

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> None: ...


class BotInviteRepository(Protocol):
    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None: ...


class AuditLogRepository(Protocol):
    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
    ) -> None: ...


class InviteTokenHasher(Protocol):
    def hash(self, raw_token: str) -> str: ...
