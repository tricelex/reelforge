"""Tests for the global DI container."""

import punq

from server.apps.main.services import BlogPostService
from server.common import container as container_module


def test_container_is_module_level_singleton() -> None:
    """The container object is always the same module-level instance."""
    assert isinstance(container_module.container, punq.Container)


def test_container_has_blog_post_service_after_app_ready() -> None:
    """After Django startup, container has BlogPostService registered."""
    service = container_module.container.resolve(BlogPostService)
    assert isinstance(service, BlogPostService)
