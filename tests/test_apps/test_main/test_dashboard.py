"""Tests for the admin dashboard callback."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from server.apps.main.dashboard import dashboard_callback
from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_dashboard_callback_context_keys_no_data() -> None:
    """Callback injects all required keys even with empty DB."""
    request = MagicMock()
    result: dict[str, Any] = dashboard_callback(request, {})

    assert isinstance(result['total_posts'], int)
    assert result['total_posts'] == 0
    assert isinstance(result['recent_posts'], list)
    assert result['recent_posts'] == []
    assert isinstance(result['total_users'], int)


@pytest.mark.django_db
def test_dashboard_callback_context_values_with_data() -> None:
    """Callback returns accurate counts and at most 5 recent posts."""
    BlogPost.objects.create(title='Post A', body='body a')
    BlogPost.objects.create(title='Post B', body='body b')

    request = MagicMock()
    result: dict[str, Any] = dashboard_callback(request, {})

    assert result['total_posts'] == 2
    assert len(result['recent_posts']) == 2
    assert result['recent_posts'][0]['title'] in {'Post A', 'Post B'}
    assert 'id' in result['recent_posts'][0]
    assert 'title' in result['recent_posts'][0]
    assert 'created_at' in result['recent_posts'][0]
