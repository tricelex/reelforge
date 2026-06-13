from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient
from faker import Faker

from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_blog_post_list_empty(dmr_client: DMRClient) -> None:
    """Returns an empty list when there are no blog posts."""
    response = dmr_client.get(reverse('api:main:blog_post_list'))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


@pytest.mark.django_db
def test_blog_post_list_returns_all_posts(
    dmr_client: DMRClient,
    faker: Faker,
) -> None:
    """Returns all blog posts ordered newest first."""
    post_a = BlogPost.objects.create(title=faker.word(), body=faker.text())
    post_b = BlogPost.objects.create(title=faker.word(), body=faker.text())

    response = dmr_client.get(reverse('api:main:blog_post_list'))

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data) == 2
    assert data[0]['id'] == post_b.pk
    assert data[1]['id'] == post_a.pk
    assert 'title' in data[0]
