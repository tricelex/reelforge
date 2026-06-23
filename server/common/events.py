"""In-process event bus — synchronous, suitable for side-effect coordination."""

from typing import Any, Protocol, final

import attrs


class EventBus(Protocol):
    """Contract for publishing domain events."""

    def emit(self, event: Any) -> None:
        """Publish an event to all registered subscribers."""
        ...

    def subscribe(self, event_type: type, handler: Any) -> None:
        """Register a callable to receive events of ``event_type``."""
        ...


@final
@attrs.define(slots=True)
class InProcessEventBus:
    """Synchronous in-process implementation of EventBus."""

    _handlers: dict[type, list[Any]] = attrs.Factory(dict)

    def subscribe(self, event_type: type, handler: Any) -> None:
        """Register a handler for the given event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: Any) -> None:
        """Call all handlers registered for this event's type."""
        for handler in self._handlers.get(type(event), []):
            handler(event)
