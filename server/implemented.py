"""Dependency injection wiring — registers all concrete implementations."""

from punq import Container, Scope


def _inject_django(container: Container) -> None:
    from django.conf import LazySettings, settings

    container.register(
        LazySettings,
        instance=settings,
        scope=Scope.singleton,
    )


def _inject_main(container: Container) -> None:
    from server.apps.main.services import BlogPostService
    from server.common.events import EventBus, InProcessEventBus

    container.register(EventBus, instance=InProcessEventBus())
    container.register(BlogPostService, scope=Scope.singleton)


def _inject_clips(container: Container) -> None:
    from server.apps.clips.services import ClipCandidateService

    container.register(ClipCandidateService, scope=Scope.singleton)


def populate_dependencies(container: Container) -> Container:
    """Populate the container with all application dependencies."""
    _inject_django(container)
    _inject_main(container)
    _inject_clips(container)
    return container
