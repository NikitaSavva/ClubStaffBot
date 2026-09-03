from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from application.athlete_notifications import (
    AthleteNotificationCandidate,
    FindAthleteNotificationCandidatesResult,
    NotifyAthleteBeforeSessionResult,
    NotifyAthleteOutcome,
    RetryableAthleteNotificationDeliveryError,
)
from presentation.celery.tasks import athlete_notifications

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


def test_poll_enqueues_one_task_per_athlete_session_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find() -> FindAthleteNotificationCandidatesResult:
        return FindAthleteNotificationCandidatesResult(
            NOW,
            (
                AthleteNotificationCandidate(42, 9),
                AthleteNotificationCandidate(42, 10),
            ),
        )

    delay = Mock()
    monkeypatch.setattr(athlete_notifications, "run_find", find)
    monkeypatch.setattr(
        athlete_notifications.notify_athlete_before_session,
        "delay",
        delay,
    )

    result = athlete_notifications.poll_athlete_notifications()

    assert result == {"reference_now": NOW.isoformat(), "candidate_count": 2}
    assert [call.kwargs for call in delay.call_args_list] == [
        {
            "training_session_id": 42,
            "athlete_id": 9,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        {
            "training_session_id": 42,
            "athlete_id": 10,
            "delivery_attempt": 1,
            "notification_id": None,
        },
    ]


@pytest.mark.parametrize(
    ("delivery_attempt", "retry_after", "countdown"),
    [(1, None, 30), (2, None, 60), (3, None, 120), (1, 75, 75)],
)
def test_retry_preserves_pair_notification_identity_and_delay(
    monkeypatch: pytest.MonkeyPatch,
    delivery_attempt: int,
    retry_after: int | None,
    countdown: int,
) -> None:
    async def retryable_notify(**kwargs: object) -> NotifyAthleteBeforeSessionResult:
        raise RetryableAthleteNotificationDeliveryError(
            training_session_id=42,
            athlete_id=9,
            notification_id=101,
            delivery_attempt=delivery_attempt,
            reminder_window_ends_at=NOW + timedelta(minutes=10),
            retry_after_seconds=retry_after,
        )

    class Retry(Exception):
        pass

    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(athlete_notifications, "run_notify", retryable_notify)
    monkeypatch.setattr(
        athlete_notifications.notify_athlete_before_session,
        "retry",
        retry,
    )

    with pytest.raises(Retry):
        athlete_notifications.notify_athlete_before_session(
            training_session_id=42,
            athlete_id=9,
            delivery_attempt=delivery_attempt,
            notification_id=None if delivery_attempt == 1 else 101,
        )

    assert retry.call_args.kwargs == {
        "exc": retry.call_args.kwargs["exc"],
        "countdown": countdown,
        "args": (),
        "kwargs": {
            "training_session_id": 42,
            "athlete_id": 9,
            "delivery_attempt": delivery_attempt + 1,
            "notification_id": 101,
        },
    }


def test_terminal_result_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def terminal_notify(**kwargs: object) -> NotifyAthleteBeforeSessionResult:
        return NotifyAthleteBeforeSessionResult(
            outcome=NotifyAthleteOutcome.WINDOW_EXPIRED,
            training_session_id=42,
            athlete_id=9,
            attempts=1,
            notification_id=101,
        )

    retry = Mock()
    monkeypatch.setattr(athlete_notifications, "run_notify", terminal_notify)
    monkeypatch.setattr(
        athlete_notifications.notify_athlete_before_session,
        "retry",
        retry,
    )

    result = athlete_notifications.notify_athlete_before_session(
        training_session_id=42,
        athlete_id=9,
    )

    assert result["outcome"] == "WINDOW_EXPIRED"
    retry.assert_not_called()


def test_eager_retry_chain_keeps_athlete_and_notification_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int | None]] = []

    async def retry_then_succeed(
        *,
        training_session_id: int,
        athlete_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyAthleteBeforeSessionResult:
        calls.append((athlete_id, delivery_attempt, notification_id))
        if delivery_attempt == 1:
            raise RetryableAthleteNotificationDeliveryError(
                training_session_id=training_session_id,
                athlete_id=athlete_id,
                notification_id=101,
                delivery_attempt=delivery_attempt,
                reminder_window_ends_at=NOW + timedelta(minutes=10),
                retry_after_seconds=None,
            )
        return NotifyAthleteBeforeSessionResult(
            outcome=NotifyAthleteOutcome.SENT,
            training_session_id=training_session_id,
            athlete_id=athlete_id,
            attempts=delivery_attempt,
            notification_id=notification_id,
        )

    monkeypatch.setattr(athlete_notifications, "run_notify", retry_then_succeed)
    task = athlete_notifications.notify_athlete_before_session
    monkeypatch.setattr(task.app.conf, "task_always_eager", True)

    result = task.apply(
        kwargs={
            "training_session_id": 42,
            "athlete_id": 9,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        throw=False,
    )

    assert result.successful()
    assert calls == [(9, 1, None), (9, 2, 101)]
