"""Business logic and data access for the main app."""

from typing import final

import attrs

from server.apps.main.logic.events import BlogPostCreated
from server.apps.main.logic.value_objects import (
    BlogPostCreatePayload,
    BlogPostFullPayload,
    BlogPostSummaryPayload,
)
from server.apps.main.models import BlogPost
from server.common.events import EventBus


@final
@attrs.define(slots=True, frozen=True)
class BlogPostService:
    """Handles all blog post operations — reads and writes."""

    _events: EventBus

    def create(self, payload: BlogPostCreatePayload) -> BlogPostFullPayload:
        """Create a new blog post and emit a domain event."""
        post = BlogPost.objects.create(
            title=payload.title,
            body=payload.body,
        )
        result = BlogPostFullPayload(
            id=post.pk,
            title=post.title,
            body=post.body,
        )
        self._events.emit(BlogPostCreated(blog_post_id=result.id))
        return result

    def get_by_id(self, post_id: int) -> BlogPostFullPayload:
        """Return a post by pk. Raises BlogPost.DoesNotExist if missing."""
        post = BlogPost.objects.get(pk=post_id)
        return BlogPostFullPayload(id=post.pk, title=post.title, body=post.body)

    def list_all(self) -> list[BlogPostSummaryPayload]:
        """Return all blog posts ordered newest first."""
        return [
            BlogPostSummaryPayload(id=row['id'], title=row['title'])
            for row in BlogPost.objects.values('id', 'title').order_by('-id')
        ]
