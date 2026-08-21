from dataclasses import dataclass
from datetime import datetime

from domain.identity import SystemRoleCode


@dataclass(frozen=True, slots=True)
class RegisterBotUserResult:
    user_id: int
    telegram_id: int
    role_code: SystemRoleCode
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class UnlinkedAthlete:
    athlete_id: int
    first_name: str
    last_name: str | None

    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.last_name, self.first_name) if part
        )


@dataclass(frozen=True, slots=True)
class CreateAthleteAccountLinkInviteResult:
    invite_id: int
    athlete_id: int
    raw_token: str


@dataclass(frozen=True, slots=True)
class LinkAthleteAccountResult:
    user_id: int
    athlete_id: int
    telegram_id: int
    role_code: SystemRoleCode
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class MenuItem:
    action_id: str
    title: str


@dataclass(frozen=True, slots=True)
class MenuContext:
    items: tuple[MenuItem, ...]
