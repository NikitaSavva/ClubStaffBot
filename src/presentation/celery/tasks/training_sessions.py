import asyncio

import structlog
from celery import shared_task
from dishka import AsyncContainer

from application.training_sessions import (
    GenerateTrainingSessionsCommand,
    GenerateTrainingSessionsInteractor,
    GenerateTrainingSessionsResult,
    MissingTrainingGroupTrainersError,
    TrainingSessionGenerationWindowResolver,
)
from bootstrap.config import Settings
from bootstrap.container import create_container

GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK = (
    "training_sessions.generate_next_week"
)
type TaskResult = dict[str, int | str]
logger = structlog.get_logger()


async def generate_with_container(
    container: AsyncContainer,
) -> GenerateTrainingSessionsResult:
    async with container() as request_container:
        resolver = await request_container.get(
            TrainingSessionGenerationWindowResolver
        )
        interactor = await request_container.get(
            GenerateTrainingSessionsInteractor
        )
        window = resolver.next_week_window()
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
        return await generate_with_container(container)
    finally:
        await container.close()


@shared_task(name=GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK)
def generate_next_week_training_sessions() -> TaskResult:
    try:
        result = asyncio.run(run())
    except MissingTrainingGroupTrainersError as error:
        logger.error(
            "training_session_generation_missing_trainers",
            training_groups=[
                {
                    "training_group_id": group.training_group_id,
                    "direction_name": group.direction_name,
                    "group_name": group.group_name,
                    "schedule": [
                        {
                            "weekday": rule.weekday,
                            "start_time": rule.start_time.isoformat(),
                            "end_time": rule.end_time.isoformat(),
                        }
                        for rule in group.schedule
                    ],
                }
                for group in error.training_groups
            ],
        )
        raise

    logger.info(
        "training_sessions_generated",
        date_from=result.date_from.isoformat(),
        date_to=result.date_to.isoformat(),
        created_count=result.created_count,
        skipped_count=result.skipped_count,
    )
    return {
        "date_from": result.date_from.isoformat(),
        "date_to": result.date_to.isoformat(),
        "created_count": result.created_count,
        "skipped_count": result.skipped_count,
    }
