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
    from server.apps.main.infra import mappers, repository
    from server.apps.main.infra import store as write_store
    from server.apps.main.logic import ports
    from server.apps.main.logic.usecases import blogpost_create, blogpost_get

    # Internal infra components
    container.register(repository.BlogPostRepo, scope=Scope.singleton)
    container.register(mappers.BlogPostMapper, scope=Scope.singleton)

    # Register BlogPostStore Protocol → concrete implementation
    container.register(
        ports.BlogPostStore,
        factory=write_store.BlogPostWriteStoreImpl,
        scope=Scope.singleton,
    )

    # Use cases — punq resolves BlogPostStore from registry automatically
    container.register(blogpost_create.CreateBlogPost, scope=Scope.singleton)
    container.register(blogpost_get.GetBlogPost, scope=Scope.singleton)


def populate_dependencies(container: Container) -> Container:
    """Populate the container with all application dependencies."""
    _inject_django(container)
    _inject_main(container)
    return container
