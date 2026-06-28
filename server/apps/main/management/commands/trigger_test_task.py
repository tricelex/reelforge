"""Management command to enqueue the add smoke-test task."""

from typing import override

from django.core.management.base import BaseCommand

from server.apps.main.tasks import add
from server.common.taskiq_sender import kiq_task


class Command(BaseCommand):
    """Management command to trigger the add smoke-test task."""

    help = 'Enqueue the add smoke-test task to verify web→worker connectivity.'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Enqueue add(5, 3) via the task broker and confirm to stdout."""
        kiq_task(add, 5, 3)
        self.stdout.write(
            self.style.SUCCESS(
                'Task enqueued (add 5+3). Watch the worker logs for: add_task_executed result=8',
            ),
        )
