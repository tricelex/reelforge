"""Django app config for the rendering service."""

from django.apps import AppConfig


class RenderingConfig(AppConfig):
    """FFmpeg assembly service functions."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.rendering'
    verbose_name = 'Rendering'
