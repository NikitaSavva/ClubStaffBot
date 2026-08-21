from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterBotUserCommand:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    invite_token: str


@dataclass(frozen=True, slots=True)
class CreateAthleteAccountLinkInviteCommand:
    actor_telegram_id: int
    athlete_id: int


@dataclass(frozen=True, slots=True)
class LinkAthleteAccountCommand:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    invite_token: str
