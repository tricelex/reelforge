from __future__ import annotations

from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone

logger = get_task_logger(__name__)


# ── Orchestrator ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue="orchestration")
def run_pipeline_orchestrator(self, channel_id: str, pipeline_run_id: str) -> None:
    """Master task: runs the OrchestratorAgent for a pipeline run."""
    import asyncio

    from reelforge.agents.orchestrator import run_orchestrator

    try:
        asyncio.run(run_orchestrator(channel_id, pipeline_run_id))
    except Exception as exc:
        logger.exception("Orchestrator failed")
        self.retry(exc=exc)


# ── Research ────────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, queue="research")
def run_research_job(self, channel_id: str, research_job_id: str) -> None:
    from agents import Runner
    from reelforge.channels.models import Channel
    from reelforge.research.models import ResearchJob

    job = ResearchJob.objects.get(id=research_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        channel = Channel.objects.prefetch_related("competitors").get(id=channel_id)
        # Agent handles the research, saves results to job
        import asyncio

        from agents import Runner
        from reelforge.agents.research_agent import build_research_agent

        agent = build_research_agent(channel)
        result = asyncio.run(
            Runner.run(
                agent,
                input=f"Research topics for channel {channel.name}. Niches: {channel.target_niches}",
                max_turns=20,
            )
        )
        # Parse result and save topics
        _save_research_results(job, result, channel)
        job.mark_completed()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


# ── Video Rendering ─────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    queue="rendering",
    time_limit=7200,  # 2 hour hard limit
    soft_time_limit=6600,
)
def render_video(self, production_job_id: str) -> None:
    """CPU-intensive video render task — runs on dedicated rendering queue."""
    from reelforge.production.models import ProductionJob
    from reelforge.services.media.video import VideoRenderer

    job = ProductionJob.objects.select_related("asset_job__script_job__topic__channel").get(id=production_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        renderer = VideoRenderer(job)
        renderer.render()  # See Section 6 for implementation
        job.mark_completed()

        # Chain to QA immediately
        run_video_qa.delay(production_job_id)

    except Exception as exc:
        job.mark_failed(str(exc))
        if job.can_retry():
            job.increment_retry()
            raise self.retry(exc=exc, countdown=600)


@shared_task(bind=True, max_retries=2, queue="rendering")
def run_video_qa(self, production_job_id: str) -> None:
    from reelforge.production.models import ProductionJob
    from reelforge.services.media.video import VideoQA

    job = ProductionJob.objects.get(id=production_job_id)
    qa = VideoQA(job)
    results = qa.run_all_checks()
    job.qa_results = results
    job.qa_passed = all(results.values())
    job.save(update_fields=["qa_results", "qa_passed", "updated_at"])

    if job.qa_passed:
        from reelforge.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(production_job=job)
        run.advance_to("UPLOADING")
        upload_video.delay(str(run.distribution_job.id))
    else:
        job.mark_paused(f"QA failed: {results}")


# ── Upload ───────────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=5, default_retry_delay=120, queue="uploads")
def upload_video(self, distribution_job_id: str) -> None:
    from reelforge.distribution.models import DistributionJob
    from reelforge.services.youtube.uploader import YouTubeUploader

    job = DistributionJob.objects.select_related("channel", "production_job").get(id=distribution_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        uploader = YouTubeUploader(channel=job.channel)
        youtube_id = uploader.upload(job)
        job.youtube_video_id = youtube_id
        job.youtube_video_url = f"https://youtube.com/watch?v={youtube_id}"
        job.youtube_upload_status = "COMPLETED"
        job.published_at = timezone.now()
        job.save()

        # Chain post-upload tasks
        (
            set_video_thumbnail.si(distribution_job_id)
            | post_pinned_comment.si(distribution_job_id)
            | add_to_playlist.si(distribution_job_id)
            | upload_youtube_short.si(distribution_job_id)
            | cross_post_social.si(distribution_job_id)
        ).delay()

        job.mark_completed()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


# ── Analytics ────────────────────────────────────────────────────────────────


@shared_task(queue="analytics")
def sync_channel_analytics(channel_id: str) -> None:
    """Pull analytics for all published videos on a channel."""
    from reelforge.channels.models import Channel
    from reelforge.distribution.models import DistributionJob
    from reelforge.services.youtube.analytics import YouTubeAnalyticsClient

    channel = Channel.objects.get(id=channel_id)
    client = YouTubeAnalyticsClient(channel=channel)

    published_jobs = DistributionJob.objects.filter(channel=channel, status="COMPLETED", youtube_video_id__isnull=False)

    for job in published_jobs:
        days_since = (timezone.now() - job.published_at).days
        for snapshot_day in [1, 7, 30]:
            if days_since >= snapshot_day:
                _create_or_update_snapshot(client, job, snapshot_day)


# ── Scheduled Tasks (via celery beat) ───────────────────────────────────────


@shared_task(queue="orchestration")
def daily_pipeline_trigger() -> None:
    """Runs every day at 6AM — checks each active channel and triggers pipelines."""
    from reelforge.channels.models import Channel
    from reelforge.pipeline.services import PipelineService

    for channel in Channel.objects.filter(status=Channel.Status.ACTIVE):
        service = PipelineService(channel)
        service.trigger_daily_batch()


@shared_task(queue="analytics")
def weekly_analytics_sync() -> None:
    from reelforge.channels.models import Channel

    for channel in Channel.objects.filter(status=Channel.Status.ACTIVE):
        sync_channel_analytics.delay(str(channel.id))


# ── Helper Functions ─────────────────────────────────────────────────────────


def _save_research_results(job: Any, result: dict[str, Any], channel: Any) -> None:
    """Save research results to database.

    Args:
        job: ResearchJob instance
        result: Agent result dict with research findings
        channel: Channel instance

    TODO: Implement full research result parsing and TopicIdea creation.
    """
    from reelforge.research.models import TopicIdea

    logger.warning("_save_research_results called (placeholder) - job=%s, channel=%s", job.id, channel.name)

    # Placeholder: Create a single mock TopicIdea
    TopicIdea.objects.create(
        research_job=job,
        channel=channel,
        title_idea="Mock Topic Idea",
        target_keyword="mock keyword",
        estimated_search_volume=10000,
        competition_score=0.5,
        relevance_score=0.8,
        source="mock_source",
    )


def _create_or_update_snapshot(client: Any, job: Any, snapshot_day: int) -> None:
    """Create or update analytics snapshot for a distribution job.

    Args:
        client: YouTubeAnalyticsClient instance
        job: DistributionJob instance
        snapshot_day: Number of days since publication (1, 7, or 30)

    TODO: Implement actual analytics data fetching and snapshot creation.
    """
    from reelforge.distribution.models import AnalyticsSnapshot

    logger.warning("_create_or_update_snapshot called (placeholder) - job=%s, snapshot_day=%d", job.id, snapshot_day)

    # Placeholder: Create or update snapshot with mock data
    AnalyticsSnapshot.objects.update_or_create(
        distribution_job=job,
        snapshot_day=snapshot_day,
        defaults={
            "views": 1000 * snapshot_day,
            "likes": 50 * snapshot_day,
            "comments": 10 * snapshot_day,
            "shares": 5 * snapshot_day,
            "watch_time_minutes": 500 * snapshot_day,
            "click_through_rate": 0.08,
            "avg_percentage_viewed": 0.65,
        },
    )
