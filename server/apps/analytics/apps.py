"""Django app config for the analytics app."""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Django app config for analytics materialized views."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.analytics'
    verbose_name = 'Analytics'
