from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

# Import task modules so LabelScheduleSource discovers cron labels.
import server.apps.main.tasks  # noqa: F401
from server.common.broker import broker

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)
