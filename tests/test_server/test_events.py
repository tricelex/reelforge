"""Unit tests for the in-process event bus."""

from server.apps.main.logic.events import BlogPostCreated
from server.common.events import InProcessEventBus


def test_emit_with_no_subscribers_does_not_raise() -> None:
    """Emitting an event with no subscribers is a no-op."""
    bus = InProcessEventBus()
    bus.emit(BlogPostCreated(blog_post_id=1))


def test_subscribe_and_emit_delivers_event() -> None:
    """A subscribed handler receives the emitted event."""
    bus = InProcessEventBus()
    received: list[BlogPostCreated] = []
    bus.subscribe(BlogPostCreated, received.append)
    bus.emit(BlogPostCreated(blog_post_id=42))
    assert received == [BlogPostCreated(blog_post_id=42)]


def test_emit_does_not_deliver_to_wrong_event_type() -> None:
    """A handler subscribed to one event type does not receive others."""

    class OtherEvent:
        """A different event type."""

    bus = InProcessEventBus()
    received: list[BlogPostCreated] = []
    bus.subscribe(BlogPostCreated, received.append)
    bus.emit(OtherEvent())
    assert received == []


def test_multiple_subscribers_all_receive_event() -> None:
    """Multiple handlers for the same event type each receive it."""
    bus = InProcessEventBus()
    calls: list[int] = []
    bus.subscribe(BlogPostCreated, lambda e: calls.append(1))
    bus.subscribe(BlogPostCreated, lambda e: calls.append(2))
    bus.emit(BlogPostCreated(blog_post_id=1))
    assert calls == [1, 2]
