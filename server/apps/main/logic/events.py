"""Domain events emitted by the main app's use cases."""

from typing import final

import attrs


@final
@attrs.define(frozen=True)
class BlogPostCreated:
    """Fired after a new blog post is successfully persisted."""

    blog_post_id: int
