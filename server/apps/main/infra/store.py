"""Concrete implementation of BlogPostStore."""

from typing import final

import attrs

from server.apps.main.infra.mappers import BlogPostMapper
from server.apps.main.infra.repository import BlogPostRepo
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


@final
@attrs.define(slots=True, frozen=True)
class BlogPostWriteStoreImpl:
    """Combines repository + mapper to implement BlogPostStore."""

    _repository: BlogPostRepo
    _mapper: BlogPostMapper

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Persist a new blog post."""
        return self._mapper(self._repository.create(payload))

    def get_by_id(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch a blog post by primary key."""
        return self._mapper(self._repository.get_by_id(blog_post_id))
