from datetime import datetime
from typing import Protocol

from application.identity.dto import BotUserSummary
from domain.identity import Athlete, BotInvite, Role, SystemRoleCode, User


class UserRepository(Protocol):
    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def get_by_id(self, user_id: int) -> User | None: ...

    async def get_by_id_for_update(self, user_id: int) -> User | None: ...

    async def add(self, user: User) -> int: ...


class BotUserReader(Protocol):
    async def search(self, query: str) -> tuple[BotUserSummary, ...]: ...


class AthleteRepository(Protocol):
    async def add(self, athlete: Athlete) -> int: ...

    async def get_by_id_for_update(
        self,
        athlete_id: int,
    ) -> Athlete | None: ...

    async def list_unlinked(self) -> tuple[Athlete, ...]: ...

    async def link_to_user(self, *, athlete_id: int, user_id: int) -> bool: ...


class RoleRepository(Protocol):
    async def get_by_code(self, code: SystemRoleCode) -> Role | None: ...

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]: ...

    async def is_assigned(self, *, user_id: int, role_id: int) -> bool: ...

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> bool: ...

    async def remove_from_user(
        self,
        *,
        user_id: int,
        role_id: int,
    ) -> bool: ...


class BotInviteRepository(Protocol):
    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None: ...

    async def get_by_token_hash_for_update(
        self,
        token_hash: str,
    ) -> BotInvite | None: ...

    async def add(self, invite: BotInvite) -> int: ...

    async def consume(self, *, invite_id: int, consumed_at: datetime) -> bool: ...


class AuditLogRepository(Protocol):
    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
        payload: dict[str, object] | None = None,
    ) -> None: ...


class InviteTokenHasher(Protocol):
    def hash(self, raw_token: str) -> str: ...


class InviteTokenGenerator(Protocol):
    def generate(self) -> str: ...
