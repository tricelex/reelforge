from typing import override

from django.apps import AppConfig


class ClipsConfig(AppConfig):
    """Django app config for the clips feature."""

    name = 'server.apps.clips'
    default_auto_field = 'django.db.models.BigAutoField'

    @override
    def ready(self) -> None:
        """Nothing to wire here — DI is populated by MainConfig.ready()."""
