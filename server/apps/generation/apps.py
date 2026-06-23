"""Generation app config."""

from django.apps import AppConfig


class GenerationConfig(AppConfig):
    """App for AI generation provider clients."""

    name = 'server.apps.generation'
    verbose_name = 'Generation'
