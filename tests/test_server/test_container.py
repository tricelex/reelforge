"""Tests for the global DI container."""

import punq

from server.apps.main.infra.repository import BlogPostRepo
from server.common import container as container_module


def test_container_is_module_level_singleton() -> None:
    """The container object is always the same module-level instance."""
    assert isinstance(container_module.container, punq.Container)


def test_container_has_blog_post_repo_after_app_ready() -> None:
    """After Django startup, container has BlogPostRepo registered."""
    repo = container_module.container.resolve(BlogPostRepo)
    assert isinstance(repo, BlogPostRepo)
