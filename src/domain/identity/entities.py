from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from domain.identity.errors import (
    AthleteBirthDateRequiredError,
    AthleteFirstNameRequiredError,
    AthleteLastNameRequiredError,
)


class SystemRoleCode(StrEnum):
    ATHLETE = "ATHLETE"
    TRAINER = "TRAINER"
    ADMINISTRATOR = "ADMINISTRATOR"
    OWNER = "OWNER"


class BotInvitePurpose(StrEnum):
    REGISTRATION = "REGISTRATION"
    ATHLETE_LINK = "ATHLETE_LINK"


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
    birth_date: date | None
    phone: str | None
    is_active: bool

    @classmethod
    def create_manually(
        cls,
        *,
        first_name: str,
        last_name: str,
        birth_date: date | None,
    ) -> Self:
        normalized_first_name = first_name.strip()
        if not normalized_first_name:
            raise AthleteFirstNameRequiredError
        normalized_last_name = last_name.strip()
        if not normalized_last_name:
            raise AthleteLastNameRequiredError
        if birth_date is None:
            raise AthleteBirthDateRequiredError
        return cls(
            id=None,
            athlete_public_id=uuid4(),
            user_id=None,
            first_name=normalized_first_name,
            last_name=normalized_last_name,
            birth_date=birth_date,
            phone=None,
            is_active=True,
        )

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
            birth_date=None,
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
    id: int | None
    token_hash: str
    purpose: BotInvitePurpose
    athlete_id: int | None
    is_active: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    consumed_at: datetime | None

    def is_valid(self, at: datetime) -> bool:
        has_valid_target = (
            self.purpose is BotInvitePurpose.REGISTRATION
            and self.athlete_id is None
        ) or (
            self.purpose is BotInvitePurpose.ATHLETE_LINK
            and self.athlete_id is not None
        )
        return (
            has_valid_target
            and self.is_active
            and self.revoked_at is None
            and self.consumed_at is None
            and (self.expires_at is None or self.expires_at > at)
        )
