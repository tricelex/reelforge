from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ***REMOVED***.pipeline.models import PipelineRun

logger = logging.getLogger("***REMOVED***.services.notifications")


def send_review_request(run: PipelineRun, reason: str) -> None:
    """Send notification to operator for manual review.

    Args:
        run: PipelineRun instance requiring review
        reason: Reason for review request

    TODO: Implement email, Slack, or other notification channels.
    For now, just logs to console.
    """
    logger.warning(
        f"REVIEW REQUESTED: PipelineRun {run.id} - {reason}",
        extra={
            "pipeline_run_id": str(run.id),
            "channel": run.topic.channel.name if run.topic else "Unknown",
            "current_stage": run.current_stage,
            "reason": reason,
        },
    )
    # TODO: Send email via django-anymail
    # TODO: Send Slack notification
    # TODO: Create in-app notification


def send_completion_notification(run: PipelineRun) -> None:
    """Send notification when pipeline completes successfully.

    Args:
        run: Completed PipelineRun instance

    TODO: Implement success notifications.
    """
    logger.info(
        f"PIPELINE COMPLETED: PipelineRun {run.id}",
        extra={
            "pipeline_run_id": str(run.id),
            "channel": run.topic.channel.name if run.topic else "Unknown",
            "youtube_url": run.distribution_job.youtube_video_url if run.distribution_job else None,
        },
    )


def send_error_notification(run: PipelineRun, error: str) -> None:
    """Send notification when pipeline encounters an error.

    Args:
        run: Failed PipelineRun instance
        error: Error message

    TODO: Implement error notifications with urgency.
    """
    logger.error(
        f"PIPELINE ERROR: PipelineRun {run.id} - {error}",
        extra={
            "pipeline_run_id": str(run.id),
            "channel": run.topic.channel.name if run.topic else "Unknown",
            "error": error,
        },
    )
