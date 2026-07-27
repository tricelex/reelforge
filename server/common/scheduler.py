from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

# Import task modules so LabelScheduleSource discovers cron labels.
import server.apps.main.tasks  # noqa: F401
import server.apps.pipelines.tasks_api  # noqa: F401
from server.common.broker import api_broker

scheduler = TaskiqScheduler(
    broker=api_broker,
    sources=[LabelScheduleSource(api_broker)],
)
