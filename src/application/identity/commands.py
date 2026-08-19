from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterBotUserCommand:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    invite_token: str
