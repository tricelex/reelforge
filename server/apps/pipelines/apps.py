from django.apps import AppConfig


class PipelinesConfig(AppConfig):
    """Django app config for the pipelines engine."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.pipelines'
    verbose_name = 'Pipelines'
