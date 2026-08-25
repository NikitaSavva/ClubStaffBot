from dataclasses import dataclass
from datetime import date, datetime

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
    birth_date: date | None

    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
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


@dataclass(frozen=True, slots=True)
class BotUserSummary:
    user_id: int
    first_name: str
    last_name: str
    username: str | None
    role_codes: tuple[SystemRoleCode, ...]

    @property
    def display_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
        )


@dataclass(frozen=True, slots=True)
class SearchBotUsersResult:
    users: tuple[BotUserSummary, ...]
    assignable_role_codes: tuple[SystemRoleCode, ...]


@dataclass(frozen=True, slots=True)
class AssignUserRoleResult:
    target_user_id: int
    role_code: SystemRoleCode
    role_was_assigned: bool
    current_role_codes: tuple[SystemRoleCode, ...]


@dataclass(frozen=True, slots=True)
class RemoveUserRoleResult:
    target_user_id: int
    role_code: SystemRoleCode
    role_was_removed: bool
    current_role_codes: tuple[SystemRoleCode, ...]
    target_user: BotUserSummary


@dataclass(frozen=True, slots=True)
class AssignOwnerResult:
    target_user_id: int
    owner_was_assigned: bool
    current_role_codes: tuple[SystemRoleCode, ...]
