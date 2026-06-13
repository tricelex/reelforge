"""Background tasks for the main app."""

import structlog
from asgiref.sync import async_to_sync

from server.apps.main.logic.events import BlogPostCreated
from server.common.broker import broker

logger = structlog.get_logger(__name__)


@broker.task
def add(a: int, b: int) -> int:
    """Add two integers. Used for smoke-testing the task queue."""
    return a + b


@broker.task
def notify_blog_post_created(blog_post_id: int) -> None:
    """Fetch the post and emit a structured log notification."""
    from server.apps.main.services import BlogPostService  # noqa: PLC0415
    from server.common.container import container  # noqa: PLC0415

    service = container.resolve(BlogPostService)
    post = service.get_by_id(blog_post_id)
    logger.info(
        'blog_post_notification',
        blog_post_id=blog_post_id,
        title=post.title,
    )


def handle_blog_post_created(event: BlogPostCreated) -> None:
    """EventBus handler — enqueues the notification task."""
    async_to_sync(notify_blog_post_created.kiq)(event.blog_post_id)


@broker.task(schedule=[{'cron': '*/2 * * * *'}])
def hourly_cleanup() -> None:
    """Sample scheduled task — runs at the top of every hour."""
    logger.info('hourly_cleanup_run')
