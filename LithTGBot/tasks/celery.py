from celery import Celery
from celery.schedules import crontab

from config import settings

# Инициализация Celery приложения
app = Celery(
    "tasks",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["tasks.price_tracking"]
)

# Настройка Celery
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_hijack_root_logger=False,
)

# Расписание периодических задач (Celery beat)
app.conf.beat_schedule = {
    "check-prices-every-day-at-10": {
        "task": "tasks.price_tracking.check_tracked_prices",
        "schedule": crontab(hour=10, minute=0),
    },
}
