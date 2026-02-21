from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("reelforge")

CELERYBEAT_SCHEDULE = {
    "daily-pipeline-trigger": {
        "task": "reelforge.pipeline.tasks.daily_pipeline_trigger",
        "schedule": crontab(hour=6, minute=0),
    },
    "weekly-analytics-sync": {
        "task": "reelforge.pipeline.tasks.weekly_analytics_sync",
        "schedule": crontab(day_of_week="monday", hour=9, minute=0),
    },
    "print_users_count": {
        "task": "reelforge.users.tasks.print_users_count",
        "schedule": crontab(minute="*/2"),  # Every 2 minutes
    },
}


# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.update(CELERYBEAT_SCHEDULE=CELERYBEAT_SCHEDULE)
app.autodiscover_tasks()


@setup_logging.connect
def config_loggers(*_args: Any, **_kwargs: Any) -> None:
    from logging.config import dictConfig

    from django.conf import settings

    dictConfig(settings.LOGGING)
