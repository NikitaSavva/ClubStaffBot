from datetime import date, time
from types import TracebackType
from typing import Self, cast
from unittest.mock import Mock

import pytest
from dishka import AsyncContainer

from application.training_sessions import (
    GenerateTrainingSessionsCommand,
    GenerateTrainingSessionsInteractor,
    GenerateTrainingSessionsResult,
    GenerationWindow,
    MissingTrainingGroupTrainersError,
    ScheduleRuleDescriptor,
    TrainingGroupWithoutTrainer,
    TrainingSessionGenerationWindowResolver,
)
from presentation.celery.tasks import training_sessions


class FakeWindowResolver:
    def next_week_window(self) -> GenerationWindow:
        return GenerationWindow(
            date_from=date(2026, 8, 31),
            date_to=date(2026, 9, 5),
        )


class FakeInteractor:
    def __init__(self) -> None:
        self.command: GenerateTrainingSessionsCommand | None = None

    async def __call__(
        self,
        command: GenerateTrainingSessionsCommand,
    ) -> GenerateTrainingSessionsResult:
        self.command = command
        return GenerateTrainingSessionsResult(
            date_from=command.date_from,
            date_to=command.date_to,
            created_count=32,
            skipped_count=0,
        )


class FakeRequestContainer:
    def __init__(
        self,
        resolver: FakeWindowResolver,
        interactor: FakeInteractor,
    ) -> None:
        self._resolver = resolver
        self._interactor = interactor

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
        if dependency is TrainingSessionGenerationWindowResolver:
            return self._resolver
        if dependency is GenerateTrainingSessionsInteractor:
            return self._interactor
        raise AssertionError(f"Unexpected dependency: {dependency}")


class FakeContainer:
    def __init__(self, request_container: FakeRequestContainer) -> None:
        self._request_container = request_container

    def __call__(self) -> FakeRequestContainer:
        return self._request_container


async def test_adapter_resolves_shared_interactor_and_next_week_window() -> None:
    resolver = FakeWindowResolver()
    interactor = FakeInteractor()
    container = cast(
        AsyncContainer,
        FakeContainer(FakeRequestContainer(resolver, interactor)),
    )

    result = await training_sessions.generate_with_container(container)

    assert interactor.command == GenerateTrainingSessionsCommand(
        date_from=date(2026, 8, 31),
        date_to=date(2026, 9, 5),
    )
    assert result.created_count == 32


def test_task_returns_and_logs_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def successful_run() -> GenerateTrainingSessionsResult:
        return GenerateTrainingSessionsResult(
            date_from=date(2026, 8, 31),
            date_to=date(2026, 9, 5),
            created_count=30,
            skipped_count=2,
        )

    info = Mock()
    monkeypatch.setattr(training_sessions, "run", successful_run)
    monkeypatch.setattr(training_sessions.logger, "info", info)

    result = training_sessions.generate_next_week_training_sessions.run()

    assert result == {
        "date_from": "2026-08-31",
        "date_to": "2026-09-05",
        "created_count": 30,
        "skipped_count": 2,
    }
    info.assert_called_once_with(
        "training_sessions_generated",
        date_from="2026-08-31",
        date_to="2026-09-05",
        created_count=30,
        skipped_count=2,
    )


def test_task_logs_missing_trainers_and_remains_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_error = MissingTrainingGroupTrainersError(
        (
            TrainingGroupWithoutTrainer(
                training_group_id=22,
                direction_name="Кикбоксинг",
                group_name="Мини-группа",
                schedule=(
                    ScheduleRuleDescriptor(
                        weekday=0,
                        start_time=time(14, 0),
                        end_time=time(15, 30),
                    ),
                ),
            ),
        )
    )

    async def failing_run() -> GenerateTrainingSessionsResult:
        raise controlled_error

    error_log = Mock()
    monkeypatch.setattr(training_sessions, "run", failing_run)
    monkeypatch.setattr(training_sessions.logger, "error", error_log)

    with pytest.raises(MissingTrainingGroupTrainersError):
        training_sessions.generate_next_week_training_sessions.run()

    error_log.assert_called_once()
    assert error_log.call_args.kwargs["training_groups"] == [
        {
            "training_group_id": 22,
            "direction_name": "Кикбоксинг",
            "group_name": "Мини-группа",
            "schedule": [
                {
                    "weekday": 0,
                    "start_time": "14:00:00",
                    "end_time": "15:30:00",
                }
            ],
        }
    ]
