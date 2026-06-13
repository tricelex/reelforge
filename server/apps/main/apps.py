"""Django application configuration for the main app."""

from typing import override

from django.apps import AppConfig


class MainConfig(AppConfig):
    """Configuration for the main application."""

    name = 'server.apps.main'
    default = True

    @override
    def ready(self) -> None:
        """Populate the global DI container once at startup."""
        from server import implemented
        from server.common import container as container_module

        implemented.populate_dependencies(container_module.container)

        from server.apps.main.logic.events import (
            BlogPostCreated,
        )
        from server.apps.main.tasks import (
            handle_blog_post_created,
        )
        from server.common.events import EventBus

        bus = container_module.container.resolve(EventBus)
        bus.subscribe(BlogPostCreated, handle_blog_post_created)
