"""Use case: retrieve a blog post by primary key."""

from typing import final

import attrs

from server.apps.main.logic.ports import BlogPostStore
from server.apps.main.logic.value_objects import BlogPostFullPayload


@final
@attrs.define(slots=True, frozen=True)
class GetBlogPost:
    """Retrieve ``BlogPost`` models by primary key."""

    _store: BlogPostStore

    def __call__(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch and return the blog post, or raise DoesNotExist."""
        return self._store.get_by_id(blog_post_id)
