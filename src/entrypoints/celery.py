from bootstrap.config import Settings
from presentation.celery import create_celery_app

app = create_celery_app(Settings())  # type: ignore[call-arg]
