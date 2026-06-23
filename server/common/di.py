"""Dependency injection helpers for controllers."""

from typing import Any, final

from server.common import container as container_module


class HasContainer:
    """
    Mixin that gives controllers access to the global DI container.

    Must be the first base class in the MRO.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pass through to the next class in MRO."""
        super().__init__(*args, **kwargs)

    @final
    def resolve[Thing](self, thing: type[Thing]) -> Thing:
        """Resolve a dependency from the global container."""
        return container_module.container.resolve(thing)  # type: ignore[no-any-return]
