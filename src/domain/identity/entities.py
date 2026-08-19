from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4


class SystemRoleCode(StrEnum):
    ATHLETE = "ATHLETE"
    TRAINER = "TRAINER"
    ADMINISTRATOR = "ADMINISTRATOR"


@dataclass(frozen=True, slots=True)
class User:
    id: int | None
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str
    is_active: bool
    registered_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class Athlete:
    id: int | None
    athlete_public_id: UUID
    user_id: int | None
    first_name: str
    last_name: str | None
    phone: str | None
    is_active: bool

    @classmethod
    def create_for_registered_user(
        cls,
        *,
        user_id: int,
        first_name: str,
        last_name: str | None,
    ) -> Self:
        return cls(
            id=None,
            athlete_public_id=uuid4(),
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            phone=None,
            is_active=True,
        )


@dataclass(frozen=True, slots=True)
class Role:
    id: int
    code: SystemRoleCode
    is_system: bool
    is_active: bool


@dataclass(frozen=True, slots=True)
class BotInvite:
    id: int
    token_hash: str
    is_active: bool
    expires_at: datetime | None
    revoked_at: datetime | None

    def is_valid(self, at: datetime) -> bool:
        return (
            self.is_active
            and self.revoked_at is None
            and (self.expires_at is None or self.expires_at > at)
        )
