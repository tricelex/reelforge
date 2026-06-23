"""Django app config for the publishing app."""

from django.apps import AppConfig


class PublishingConfig(AppConfig):
    """App config for publishing — YouTube upload tracking."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.publishing'
    verbose_name = 'Publishing'
