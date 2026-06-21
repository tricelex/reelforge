"""Configure Django before Taskiq imports app task modules.

Taskiq worker processes import task modules before ``WORKER_STARTUP`` runs,
so any module-level Django model import requires ``django.setup()`` first.
Import this module in the worker command before other task packages.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')


def setup_django() -> None:
    """Call ``django.setup()`` once for the current process."""
    import django
    from django.apps import apps

    if apps.ready:
        return
    django.setup()


setup_django()
