"""Tests for CQRS read query objects."""

import pytest
from faker import Faker

from server.apps.main.infra.queries import BlogPostListQuery
from server.apps.main.logic.value_objects import BlogPostSummaryPayload
from server.apps.main.models import BlogPost


@pytest.mark.django_db
def test_blog_post_list_query_returns_empty_list_when_no_posts() -> None:
    """Returns an empty list when there are no blog posts."""
    query = BlogPostListQuery()
    result = query()
    assert result == []


@pytest.mark.django_db
def test_blog_post_list_query_returns_all_posts(faker: Faker) -> None:
    """Returns a summary for each post, newest first."""
    post_a = BlogPost.objects.create(title=faker.word(), body=faker.text())
    post_b = BlogPost.objects.create(title=faker.word(), body=faker.text())
    query = BlogPostListQuery()
    result = query()
    assert len(result) == 2
    assert all(isinstance(r, BlogPostSummaryPayload) for r in result)
    assert result[0].id == post_b.pk
    assert result[1].id == post_a.pk
