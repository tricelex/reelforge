from unittest.mock import patch

import pytest

from server.apps.main.logic.events import BlogPostCreated
from server.apps.main.models import BlogPost
from server.apps.main.tasks import (
    add,
    handle_blog_post_created,
    hourly_cleanup,
    notify_blog_post_created,
)


def test_add() -> None:
    """Smoke-tests the add task by calling its unwrapped function."""
    assert add.original_func(1, 2) == 3


@pytest.mark.django_db
def test_notify_blog_post_created(blog_post: BlogPost) -> None:
    """Calls the notification task directly against a persisted BlogPost."""
    notify_blog_post_created.original_func(blog_post.pk)


def test_hourly_cleanup() -> None:
    """Smoke-tests the hourly_cleanup task by calling its unwrapped function."""
    hourly_cleanup.original_func()  # type: ignore[attr-defined]


def test_handle_blog_post_created() -> None:
    """Ensures the EventBus handler enqueues notify_blog_post_created."""
    with patch('server.apps.main.tasks.kiq_task') as mock_kiq:
        handle_blog_post_created(BlogPostCreated(blog_post_id=42))
        mock_kiq.assert_called_once_with(notify_blog_post_created, 42)
