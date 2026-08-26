from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from bootstrap.config import Settings
from presentation.celery.tasks.training_sessions import (
    GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK,
)


def create_celery_app(settings: Settings) -> Celery:
    app = Celery(
        "staff_bot",
        broker=settings.redis_url,
        include=("presentation.celery.tasks.training_sessions",),
    )
    app.conf.update(
        enable_utc=True,
        timezone=settings.club_timezone,
        beat_schedule={
            "generate-next-week-training-sessions": {
                "task": GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK,
                "schedule": crontab(
                    minute=0,
                    hour=0,
                    day_of_week="sunday",
                ),
            }
        },
    )
    return app
