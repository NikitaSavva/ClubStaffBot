from dataclasses import dataclass
from datetime import datetime

from domain.identity import SystemRoleCode


@dataclass(frozen=True, slots=True)
class RegisterBotUserResult:
    user_id: int
    telegram_id: int
    role_code: SystemRoleCode
    registered_at: datetime
