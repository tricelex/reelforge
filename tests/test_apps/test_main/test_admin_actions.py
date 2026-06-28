"""Tests for custom Django admin actions on the main app."""

from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from server.apps.main.models import BlogPost
from server.apps.main.tasks import add


@pytest.mark.django_db
def test_trigger_smoke_test_action_enqueues_add(
    admin_client: Client,
    blog_post: BlogPost,
) -> None:
    """trigger_smoke_test action calls kiq_task(add, 5, 3) and redirects."""
    url = reverse('admin:main_blogpost_changelist')
    with patch('server.apps.main.admin.kiq_task') as mock_kiq:
        response = admin_client.post(
            url,
            {
                'action': 'trigger_smoke_test',
                '_selected_action': [str(blog_post.pk)],
            },
        )

    assert response.status_code == HTTPStatus.FOUND
    mock_kiq.assert_called_once_with(add, 5, 3)
