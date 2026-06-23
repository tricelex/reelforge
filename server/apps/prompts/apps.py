from django.apps import AppConfig


class PromptsConfig(AppConfig):
    """AppConfig for the prompts app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.prompts'
    verbose_name = 'Prompts'
