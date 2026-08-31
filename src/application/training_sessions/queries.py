from dataclasses import dataclass

from domain.identity import SystemRoleCode


@dataclass(frozen=True, slots=True)
class GetCurrentWeekScheduleQuery:
    actor_telegram_id: int
    selected_role: SystemRoleCode
