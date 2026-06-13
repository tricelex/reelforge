"""Tests for BlogPostWriteStoreImpl."""

import pytest

from server.apps.main.infra.mappers import BlogPostMapper
from server.apps.main.infra.repository import BlogPostRepo
from server.apps.main.infra.store import BlogPostWriteStoreImpl
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


def _make_store() -> BlogPostWriteStoreImpl:
    return BlogPostWriteStoreImpl(
        repository=BlogPostRepo(),
        mapper=BlogPostMapper(),
    )


def test_store_satisfies_protocol() -> None:
    """BlogPostWriteStoreImpl structurally implements BlogPostStore."""
    store = _make_store()
    assert callable(store.create)
    assert callable(store.get_by_id)


@pytest.mark.django_db
def test_store_create_persists_and_returns_dto() -> None:
    """create() saves to DB and returns BlogPostFullPayload."""
    store = _make_store()
    payload = BlogPostCreatePayload(title='Hello', body='World')
    result = store.create(payload)
    assert isinstance(result, BlogPostFullPayload)
    assert result.title == 'Hello'
    assert result.body == 'World'
    assert result.id > 0


@pytest.mark.django_db
def test_store_get_by_id_returns_dto() -> None:
    """get_by_id() fetches from DB and returns BlogPostFullPayload."""
    store = _make_store()
    payload = BlogPostCreatePayload(title='Fetch Me', body='Body')
    created = store.create(payload)
    fetched = store.get_by_id(created.id)
    assert fetched == created
