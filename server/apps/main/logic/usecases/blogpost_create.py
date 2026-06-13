"""Use case: create a new blog post."""

from typing import final

import attrs

from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


@final
@attrs.define(slots=True, frozen=True)
class CreateBlogPost:
    """Creates ``BlogPost`` instances."""

    _store: BlogPostStore

    def __call__(
        self,
        parsed_body: BlogPostCreatePayload,
    ) -> BlogPostFullPayload:
        """
        Validate and persist a new blog post.

        Business logic (credits, quotas, etc.) belongs here before
        the ``self._store.create()`` call.
        """
        return self._store.create(parsed_body)
