import asyncio
import sys

from dishka import AsyncContainer

from application.training_sessions import (
    GenerateTrainingSessionsCommand,
    GenerateTrainingSessionsInteractor,
    GenerateTrainingSessionsResult,
    MissingTrainingGroupTrainersError,
    ScheduleRuleDescriptor,
    TrainingGroupWithoutTrainer,
    TrainingSessionGenerationWindowResolver,
)
from bootstrap.config import Settings
from bootstrap.container import create_container

WEEKDAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


async def generate_training_sessions(
    container: AsyncContainer,
) -> GenerateTrainingSessionsResult:
    async with container() as request_container:
        resolver = await request_container.get(
            TrainingSessionGenerationWindowResolver
        )
        interactor = await request_container.get(
            GenerateTrainingSessionsInteractor
        )
        window = resolver.bootstrap_window()
        return await interactor(
            GenerateTrainingSessionsCommand(
                date_from=window.date_from,
                date_to=window.date_to,
            )
        )


async def run() -> GenerateTrainingSessionsResult:
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await generate_training_sessions(container)
    finally:
        await container.close()


def format_missing_training_group(
    training_group: TrainingGroupWithoutTrainer,
) -> str:
    schedule = ", ".join(
        _format_schedule_rule(rule) for rule in training_group.schedule
    )
    return (
        f"{training_group.direction_name} / {training_group.group_name} "
        f"[group_id={training_group.training_group_id}]: {schedule}"
    )


def _format_schedule_rule(rule: ScheduleRuleDescriptor) -> str:
    return (
        f"{WEEKDAY_NAMES[rule.weekday]} "
        f"{rule.start_time:%H:%M}-{rule.end_time:%H:%M}"
    )


def main() -> int:
    try:
        result = asyncio.run(run())
    except MissingTrainingGroupTrainersError as error:
        print(
            "TrainingSession generation aborted: assign a Trainer to every "
            "applicable TrainingGroup.",
            file=sys.stderr,
        )
        for training_group in error.training_groups:
            print(
                f"- {format_missing_training_group(training_group)}",
                file=sys.stderr,
            )
        return 2

    print(f"Generation window: {result.date_from} .. {result.date_to}")
    print(f"Created: {result.created_count}")
    print(f"Skipped existing: {result.skipped_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
