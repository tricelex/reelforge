"""Write-side ports (Protocols) for the main app's domain."""

from typing import Protocol

from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
)


class BlogPostStore(Protocol):
    """Write and fetch operations for blog posts, returning value objects."""

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Persist a new blog post and return it as a value object."""
        ...

    def get_by_id(self, blog_post_id: int) -> BlogPostFullPayload:
        """Fetch an existing blog post by primary key."""
        ...
