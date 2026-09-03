from datetime import datetime
from typing import Protocol

from application.athlete_notifications.dto import (
    AthleteNotificationCandidate,
    AthleteNotificationMessage,
    AthleteNotificationRecipient,
    AthleteNotificationSession,
)


class AthleteNotificationReader(Protocol):
    async def find_due_candidates(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        grace_window_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[AthleteNotificationCandidate, ...]: ...

    async def get_session(
        self,
        training_session_id: int,
    ) -> AthleteNotificationSession | None: ...

    async def get_eligible_recipient(
        self,
        *,
        athlete_id: int,
        training_group_id: int,
        reference_now: datetime,
    ) -> AthleteNotificationRecipient | None: ...


class AthleteNotifier(Protocol):
    async def send(
        self,
        *,
        telegram_id: int,
        message: AthleteNotificationMessage,
    ) -> None: ...
