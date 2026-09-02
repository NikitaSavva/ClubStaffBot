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
    )

    assert find_result.training_session_ids == (10, 20)
    assert notify.command == NotifyTrainerBeforeSessionCommand(42, 3)
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
    assert [call.args for call in delay.call_args_list] == [(10,), (20,)]


def test_retryable_failure_schedules_numbered_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def retryable_notify(
        *,
        training_session_id: int,
        delivery_attempt: int,
    ) -> NotifyTrainerBeforeSessionResult:
        raise RetryableTrainerNotificationDeliveryError(
            training_session_id=training_session_id,
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
        trainer_notifications.notify_trainer_before_session.run(42, 2)

    assert retry.call_args.kwargs["countdown"] == 60
    assert retry.call_args.kwargs["kwargs"] == {
        "training_session_id": 42,
        "delivery_attempt": 3,
    }
