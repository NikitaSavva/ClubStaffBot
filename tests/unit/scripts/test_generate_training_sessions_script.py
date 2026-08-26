import sys
from datetime import date, time
from types import TracebackType
from typing import Self, cast

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
from scripts import generate_training_sessions


class FakeWindowResolver:
    def bootstrap_window(self) -> GenerationWindow:
        return GenerationWindow(
            date_from=date(2026, 8, 24),
            date_to=date(2026, 8, 29),
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


async def test_script_uses_bootstrap_window_and_shared_interactor() -> None:
    resolver = FakeWindowResolver()
    interactor = FakeInteractor()
    container = cast(
        AsyncContainer,
        FakeContainer(FakeRequestContainer(resolver, interactor)),
    )

    result = await generate_training_sessions.generate_training_sessions(
        container
    )

    assert interactor.command == GenerateTrainingSessionsCommand(
        date_from=date(2026, 8, 24),
        date_to=date(2026, 8, 29),
    )
    assert result.created_count == 32


def test_main_prints_generation_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def successful_run() -> GenerateTrainingSessionsResult:
        return GenerateTrainingSessionsResult(
            date_from=date(2026, 8, 24),
            date_to=date(2026, 8, 29),
            created_count=32,
            skipped_count=0,
        )

    monkeypatch.setattr(generate_training_sessions, "run", successful_run)
    monkeypatch.setattr(sys, "argv", ["generate_training_sessions"])

    assert generate_training_sessions.main() == 0
    output = capsys.readouterr()
    assert "Generation window: 2026-08-24 .. 2026-08-29" in output.out
    assert "Created: 32" in output.out
    assert "Skipped existing: 0" in output.out
    assert output.err == ""


def test_main_reports_all_missing_trainers_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = MissingTrainingGroupTrainersError(
        (
            TrainingGroupWithoutTrainer(
                training_group_id=22,
                direction_name="Кикбоксинг",
                group_name="Дети 6–9 лет",
                schedule=(
                    ScheduleRuleDescriptor(
                        weekday=1,
                        start_time=time(17, 30),
                        end_time=time(18, 45),
                    ),
                    ScheduleRuleDescriptor(
                        weekday=3,
                        start_time=time(17, 30),
                        end_time=time(18, 45),
                    ),
                ),
            ),
        )
    )

    async def failing_run() -> GenerateTrainingSessionsResult:
        raise error

    monkeypatch.setattr(generate_training_sessions, "run", failing_run)

    assert generate_training_sessions.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "assign a Trainer" in output.err
    assert "Кикбоксинг / Дети 6–9 лет [group_id=22]" in output.err
    assert "TUE 17:30-18:45, THU 17:30-18:45" in output.err
    assert "Traceback" not in output.err
