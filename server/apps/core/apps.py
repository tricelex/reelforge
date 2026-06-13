"""Django application configuration for the core app."""

from typing import override

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration for the core application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.core'
    verbose_name = 'Core'

    @override
    def ready(self) -> None:
        """Initialise Sentry error tracking and Logfire observability."""
        from server.common.observability import init_logfire, init_sentry

        init_sentry()
        init_logfire()
