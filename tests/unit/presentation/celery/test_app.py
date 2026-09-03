from bootstrap.config import Settings
from presentation.celery.app import create_celery_app
from presentation.celery.tasks.athlete_notifications import (
    NOTIFY_ATHLETE_BEFORE_SESSION_TASK,
    POLL_ATHLETE_NOTIFICATIONS_TASK,
)
from presentation.celery.tasks.trainer_notifications import (
    NOTIFY_TRAINER_BEFORE_SESSION_TASK,
    POLL_TRAINER_NOTIFICATIONS_TASK,
)
from presentation.celery.tasks.training_sessions import (
    GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK,
)


def test_beat_generates_next_week_every_sunday_at_club_midnight() -> None:
    settings = Settings(
        postgres_host="database",
        postgres_port=5432,
        postgres_db="staff_bot",
        postgres_user="user",
        postgres_password="password",
        redis_host="cache",
        redis_port=6379,
        redis_db=0,
        club_timezone="Europe/Moscow",
        telegram_bot_token="123456789:test-token",
        telegram_webapp_base_url="https://scanner.example.test",
        athlete_qr_signing_secret="s" * 32,
        _env_file=None,
    )

    app = create_celery_app(settings)

    assert app.conf.timezone == "Europe/Moscow"
    assert app.conf.enable_utc is True
    assert GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK in app.tasks
    assert POLL_ATHLETE_NOTIFICATIONS_TASK in app.tasks
    assert NOTIFY_ATHLETE_BEFORE_SESSION_TASK in app.tasks
    assert POLL_TRAINER_NOTIFICATIONS_TASK in app.tasks
    assert NOTIFY_TRAINER_BEFORE_SESSION_TASK in app.tasks
    schedule = app.conf.beat_schedule[
        "generate-next-week-training-sessions"
    ]
    assert schedule["task"] == GENERATE_NEXT_WEEK_TRAINING_SESSIONS_TASK
    assert schedule["schedule"].minute == {0}
    assert schedule["schedule"].hour == {0}
    assert schedule["schedule"].day_of_week == {0}
    notification_schedule = app.conf.beat_schedule[
        "poll-trainer-notifications"
    ]
    assert notification_schedule["task"] == POLL_TRAINER_NOTIFICATIONS_TASK
    assert notification_schedule["schedule"].minute == set(range(60))
    athlete_notification_schedule = app.conf.beat_schedule[
        "poll-athlete-notifications"
    ]
    assert athlete_notification_schedule["task"] == POLL_ATHLETE_NOTIFICATIONS_TASK
    assert athlete_notification_schedule["schedule"].minute == set(range(60))
