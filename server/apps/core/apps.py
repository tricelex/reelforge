"""Django application configuration for core infrastructure."""

from typing import override

from django.apps import AppConfig

from server.common.observability import init_logfire, init_sentry


class CoreConfig(AppConfig):
    """Permanent infrastructure app — initialises observability at startup."""

    name = 'server.apps.core'
    default = True

    @override
    def ready(self) -> None:
        """Initialise Sentry and Logfire once at Django startup."""
        init_sentry()
        init_logfire()
