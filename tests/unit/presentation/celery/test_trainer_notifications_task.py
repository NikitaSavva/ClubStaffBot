from datetime import UTC, datetime
from types import TracebackType
from typing import Self, cast
from unittest.mock import Mock

import pytest
from celery.exceptions import Retry  # type: ignore[import-untyped]
from dishka import AsyncContainer

from application.trainer_notifications import (
    FindSessionsForTrainerNotificationInteractor,
    FindTrainerNotificationSessionsResult,
    NotifyTrainerBeforeSessionCommand,
    NotifyTrainerBeforeSessionInteractor,
    NotifyTrainerBeforeSessionResult,
    NotifyTrainerOutcome,
    RetryableTrainerNotificationDeliveryError,
)
from presentation.celery.tasks import trainer_notifications

NOW = datetime(2026, 9, 2, 15, 55, tzinfo=UTC)


class FakeFindInteractor:
    async def __call__(self) -> FindTrainerNotificationSessionsResult:
        return FindTrainerNotificationSessionsResult(NOW, (10, 20))


class FakeNotifyInteractor:
    def __init__(self) -> None:
        self.command: NotifyTrainerBeforeSessionCommand | None = None

    async def __call__(
        self,
        command: NotifyTrainerBeforeSessionCommand,
    ) -> NotifyTrainerBeforeSessionResult:
        self.command = command
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.SENT,
            training_session_id=command.training_session_id,
            attempts=command.delivery_attempt,
        )


class FakeRequestContainer:
    def __init__(
        self,
        find: FakeFindInteractor,
        notify: FakeNotifyInteractor,
    ) -> None:
        self.find = find
        self.notify = notify

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def get(self, dependency: object) -> object:
        if dependency is FindSessionsForTrainerNotificationInteractor:
            return self.find
        if dependency is NotifyTrainerBeforeSessionInteractor:
            return self.notify
        raise AssertionError(f"Unexpected dependency: {dependency}")


class FakeContainer:
    def __init__(self, request: FakeRequestContainer) -> None:
        self.request = request

    def __call__(self) -> FakeRequestContainer:
        return self.request


async def test_adapters_resolve_application_operations() -> None:
    find = FakeFindInteractor()
    notify = FakeNotifyInteractor()
    container = cast(
        AsyncContainer,
        FakeContainer(FakeRequestContainer(find, notify)),
    )

    find_result = await trainer_notifications.find_with_container(container)
    notify_result = await trainer_notifications.notify_with_container(
        container,
        training_session_id=42,
        delivery_attempt=3,
        notification_id=100,
    )

    assert find_result.training_session_ids == (10, 20)
    assert notify.command == NotifyTrainerBeforeSessionCommand(42, 3, 100)
    assert notify_result.outcome is NotifyTrainerOutcome.SENT


def test_poll_enqueues_one_task_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def successful_find() -> FindTrainerNotificationSessionsResult:
        return FindTrainerNotificationSessionsResult(NOW, (10, 20))

    delay = Mock()
    monkeypatch.setattr(trainer_notifications, "run_find", successful_find)
    monkeypatch.setattr(
        trainer_notifications.notify_trainer_before_session,
        "delay",
        delay,
    )

    result = trainer_notifications.poll_trainer_notifications.run()

    assert result["candidate_count"] == 2
    assert [call.kwargs for call in delay.call_args_list] == [
        {
            "training_session_id": 10,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        {
            "training_session_id": 20,
            "delivery_attempt": 1,
            "notification_id": None,
        },
    ]


def test_retryable_failure_schedules_numbered_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def retryable_notify(
        *,
        training_session_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyTrainerBeforeSessionResult:
        assert notification_id == 100
        raise RetryableTrainerNotificationDeliveryError(
            training_session_id=training_session_id,
            notification_id=100,
            delivery_attempt=delivery_attempt,
            starts_at=NOW,
            retry_after_seconds=None,
        )

    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(trainer_notifications, "run_notify", retryable_notify)
    monkeypatch.setattr(
        trainer_notifications.notify_trainer_before_session,
        "retry",
        retry,
    )

    with pytest.raises(Retry):
        trainer_notifications.notify_trainer_before_session.run(
            training_session_id=42,
            delivery_attempt=2,
            notification_id=100,
        )

    assert retry.call_args.kwargs["countdown"] == 60
    assert retry.call_args.kwargs["args"] == ()
    assert retry.call_args.kwargs["kwargs"] == {
        "training_session_id": 42,
        "delivery_attempt": 3,
        "notification_id": 100,
    }


def test_eager_retry_chain_executes_attempts_two_and_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int | None]] = []

    async def retry_then_succeed(
        *,
        training_session_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyTrainerBeforeSessionResult:
        assert training_session_id == 42
        calls.append((delivery_attempt, notification_id))
        if delivery_attempt < 3:
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=training_session_id,
                notification_id=100,
                delivery_attempt=delivery_attempt,
                starts_at=NOW,
                retry_after_seconds=None,
            )
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.SENT,
            training_session_id=training_session_id,
            attempts=delivery_attempt,
            notification_id=notification_id,
        )

    monkeypatch.setattr(
        trainer_notifications,
        "run_notify",
        retry_then_succeed,
    )
    task = trainer_notifications.notify_trainer_before_session
    monkeypatch.setattr(task.app.conf, "task_always_eager", True)

    result = task.apply(
        kwargs={
            "training_session_id": 42,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        throw=False,
    )

    assert result.successful()
    assert calls == [(1, None), (2, 100), (3, 100)]


def test_poll_eager_delivery_retries_without_argument_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int | None]] = []

    async def one_candidate() -> FindTrainerNotificationSessionsResult:
        return FindTrainerNotificationSessionsResult(NOW, (42,))

    async def retry_then_succeed(
        *,
        training_session_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyTrainerBeforeSessionResult:
        calls.append((delivery_attempt, notification_id))
        if delivery_attempt == 1:
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=training_session_id,
                notification_id=103,
                delivery_attempt=delivery_attempt,
                starts_at=NOW,
                retry_after_seconds=None,
            )
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.SENT,
            training_session_id=training_session_id,
            attempts=delivery_attempt,
            notification_id=notification_id,
        )

    monkeypatch.setattr(trainer_notifications, "run_find", one_candidate)
    monkeypatch.setattr(
        trainer_notifications,
        "run_notify",
        retry_then_succeed,
    )
    task = trainer_notifications.notify_trainer_before_session
    monkeypatch.setattr(task.app.conf, "task_always_eager", True)

    result = trainer_notifications.poll_trainer_notifications.run()

    assert result["candidate_count"] == 1
    assert calls == [(1, None), (2, 103)]


def test_eager_retry_after_keeps_server_delay_and_kwargs_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int | None]] = []
    retry_options: list[dict[str, object]] = []

    async def retry_after_then_succeed(
        *,
        training_session_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyTrainerBeforeSessionResult:
        calls.append((delivery_attempt, notification_id))
        if delivery_attempt == 1:
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=training_session_id,
                notification_id=101,
                delivery_attempt=delivery_attempt,
                starts_at=NOW,
                retry_after_seconds=90,
            )
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.SENT,
            training_session_id=training_session_id,
            attempts=delivery_attempt,
            notification_id=notification_id,
        )

    monkeypatch.setattr(
        trainer_notifications,
        "run_notify",
        retry_after_then_succeed,
    )
    task = trainer_notifications.notify_trainer_before_session
    original_retry = task.retry

    def recording_retry(*args: object, **kwargs: object) -> object:
        retry_options.append(kwargs)
        return original_retry(*args, **kwargs)

    monkeypatch.setattr(task, "retry", recording_retry)
    monkeypatch.setattr(task.app.conf, "task_always_eager", True)

    result = task.apply(
        kwargs={
            "training_session_id": 42,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        throw=False,
    )

    assert result.successful()
    assert calls == [(1, None), (2, 101)]
    assert retry_options[0]["countdown"] == 90
    assert retry_options[0]["args"] == ()
    assert retry_options[0]["kwargs"] == {
        "training_session_id": 42,
        "delivery_attempt": 2,
        "notification_id": 101,
    }


def test_eager_retry_chain_stops_after_four_delivery_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def exhaust_retries(
        *,
        training_session_id: int,
        delivery_attempt: int,
        notification_id: int | None,
    ) -> NotifyTrainerBeforeSessionResult:
        calls.append(delivery_attempt)
        if delivery_attempt < 4:
            raise RetryableTrainerNotificationDeliveryError(
                training_session_id=training_session_id,
                notification_id=102,
                delivery_attempt=delivery_attempt,
                starts_at=NOW,
                retry_after_seconds=None,
            )
        return NotifyTrainerBeforeSessionResult(
            outcome=NotifyTrainerOutcome.TERMINAL_FAILED,
            training_session_id=training_session_id,
            attempts=delivery_attempt,
            notification_id=notification_id,
        )

    monkeypatch.setattr(
        trainer_notifications,
        "run_notify",
        exhaust_retries,
    )
    task = trainer_notifications.notify_trainer_before_session
    monkeypatch.setattr(task.app.conf, "task_always_eager", True)

    result = task.apply(
        kwargs={
            "training_session_id": 42,
            "delivery_attempt": 1,
            "notification_id": None,
        },
        throw=False,
    )

    assert result.successful()
    assert calls == [1, 2, 3, 4]
    assert result.result["outcome"] == NotifyTrainerOutcome.TERMINAL_FAILED.value
