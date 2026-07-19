"""Background tasks for the main app."""

import structlog

from server.apps.main.logic.events import BlogPostCreated
from server.common.broker import broker
from server.common.taskiq_sender import kiq_task

logger = structlog.get_logger(__name__)


@broker.task
def add(a: int, b: int) -> int:
    """Add two integers. Used for smoke-testing the task queue."""
    result = a + b
    logger.info('add_task_executed', a=a, b=b, result=result)
    return result


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
    kiq_task(notify_blog_post_created, event.blog_post_id)


@broker.task(schedule=[{'cron': '0 * * * *'}])
def hourly_cleanup() -> None:
    """Evict LRU local asset cache files over the configured byte budget."""
    from server.common.asset_cache import (  # noqa: PLC0415
        cleanup_asset_cache,
    )

    removed = cleanup_asset_cache()
    logger.info('hourly_cleanup_run', removed_files=removed)
