from celery import Celery
from celery.schedules import crontab

from bootstrap.config import Settings
from presentation.celery.tasks.athlete_notifications import (
    POLL_ATHLETE_NOTIFICATIONS_TASK,
)
from presentation.celery.tasks.trainer_notifications import (
    POLL_TRAINER_NOTIFICATIONS_TASK,
)
from presentation.celery.tasks.training_sessions import (
    GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK,
)


def create_celery_app(settings: Settings) -> Celery:
    app = Celery(
        "staff_bot",
        broker=settings.redis_url,
        include=(
            "presentation.celery.tasks.training_sessions",
            "presentation.celery.tasks.trainer_notifications",
            "presentation.celery.tasks.athlete_notifications",
        ),
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
            },
            "poll-trainer-notifications": {
                "task": POLL_TRAINER_NOTIFICATIONS_TASK,
                "schedule": crontab(minute="*"),
            },
            "poll-athlete-notifications": {
                "task": POLL_ATHLETE_NOTIFICATIONS_TASK,
                "schedule": crontab(minute="*"),
            },
        },
    )
    return app
