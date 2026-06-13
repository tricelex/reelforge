"""CQRS read-side query objects for the main app."""

from typing import final

import attrs

from server.apps.main.logic.value_objects import BlogPostSummaryPayload
from server.apps.main.models import BlogPost


@final
@attrs.define(slots=True, frozen=True)
class BlogPostListQuery:
    """Returns a lightweight summary list of all blog posts."""

    def __call__(self) -> list[BlogPostSummaryPayload]:
        """Fetch all blog posts ordered newest first."""
        return [
            BlogPostSummaryPayload(id=row['id'], title=row['title'])
            for row in BlogPost.objects.values('id', 'title').order_by('-id')
        ]
