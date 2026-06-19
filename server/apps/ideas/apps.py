from django.apps import AppConfig


class IdeasConfig(AppConfig):
    """AppConfig for the ideas app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.ideas'
    verbose_name = 'Ideation'
