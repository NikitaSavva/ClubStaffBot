from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
