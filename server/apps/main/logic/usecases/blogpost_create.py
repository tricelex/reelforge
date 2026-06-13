"""Use case: create a new blog post."""

from typing import final

import attrs

from server.apps.main.logic.events import BlogPostCreated
from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)
from server.common.events import EventBus


@final
@attrs.define(slots=True, frozen=True)
class CreateBlogPost:
    """Creates ``BlogPost`` instances."""

    _store: BlogPostStore
    _events: EventBus

    def __call__(
        self,
        parsed_body: BlogPostCreatePayload,
    ) -> BlogPostFullPayload:
        """
        Validate and persist a new blog post, then emit BlogPostCreated.

        Business logic (credits, quotas, etc.) belongs here before
        the ``self._store.create()`` call.
        """
        result = self._store.create(parsed_body)
        self._events.emit(BlogPostCreated(blog_post_id=result.id))
        return result
