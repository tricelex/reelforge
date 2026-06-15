from django.apps import AppConfig


class ClipsConfig(AppConfig):
    """Django app config for the clips feature."""

    name = 'server.apps.clips'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self) -> None:
        """Wire DI services for clips."""
        from server import implemented
        from server.common import container as container_module

        implemented.populate_dependencies(container_module.container)
