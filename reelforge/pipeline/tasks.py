from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from dependency_injector.wiring import Provide
from dependency_injector.wiring import inject
from django.utils import timezone

from ***REMOVED***.agents.containers import AgentContainer

if TYPE_CHECKING:
    from ***REMOVED***.agents.providers.protocols import RedditProvider
    from ***REMOVED***.agents.providers.protocols import TrendsProvider
    from ***REMOVED***.agents.providers.protocols import VideoSearchProvider
    from ***REMOVED***.services.youtube.client import YouTubeClient

logger = get_task_logger(__name__)


# ── Orchestrator ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue="orchestration")
def run_pipeline_orchestrator(self, channel_id: str, pipeline_run_id: str) -> None:
    """Master task: runs the OrchestratorAgent for a pipeline run."""
    import asyncio

    from ***REMOVED***.agents.orchestrator import run_orchestrator

    try:
        asyncio.run(run_orchestrator(channel_id, pipeline_run_id))
    except Exception as exc:
        logger.exception("Orchestrator failed")
        self.retry(exc=exc)


# ── Research ────────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, queue="research")
@inject
def run_research_job(
    self: Any,
    channel_id: str,
    research_job_id: str,
    video_search: VideoSearchProvider = Provide[AgentContainer.video_search],
    trends: TrendsProvider = Provide[AgentContainer.trends],
    reddit: RedditProvider = Provide[AgentContainer.reddit],
) -> None:
    import asyncio

    from agents import Runner
    from ***REMOVED***.agents.research_agent import build_research_agent
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.models import ResearchJob

    job = ResearchJob.objects.get(id=research_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        channel = Channel.objects.prefetch_related("competitors").get(id=channel_id)
        agent = build_research_agent(channel, video_search, trends, reddit)
        result = asyncio.run(
            Runner.run(
                agent,
                input=f"Research topics for channel {channel.name}. Niches: {channel.target_niches}",
                max_turns=20,
            )
        )
        _save_research_results(job, result, channel)
        job.mark_completed()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="research")
def run_research_job_for_channel(self, channel_id: str) -> None:
    """Create a ResearchJob for the channel and dispatch run_research_job."""
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.choices import ResearchTrigger
    from ***REMOVED***.research.models import ResearchJob

    try:
        channel = Channel.objects.get(id=channel_id)
        job = ResearchJob.objects.create(
            channel=channel,
            trigger_source=ResearchTrigger.MANUAL,
            search_keywords=list(channel.channel_keywords[:10]),
        )
        run_research_job.delay(str(channel.id), str(job.id))
        logger.info("Research job created for channel %s: job_id=%s", channel.slug, job.id)
    except Exception as exc:
        logger.exception("Failed to create research job for channel %s", channel_id)
        raise self.retry(exc=exc) from None


# ── Script Generation ────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue="default")
def run_script_job(self, topic_id: str, pipeline_run_id: str) -> None:
    """Build ScriptAgent and run it for the given topic."""
    import asyncio

    from agents import Runner
    from ***REMOVED***.agents.script_agent import build_script_agent
    from ***REMOVED***.pipeline.models import PipelineRun
    from ***REMOVED***.research.models import TopicIdea
    from ***REMOVED***.scripts.models import ScriptJob

    topic = TopicIdea.objects.select_related("channel").get(id=topic_id)
    channel = topic.channel

    # Create ScriptJob if not yet exists for this topic
    job, _ = ScriptJob.objects.get_or_create(
        topic=topic,
        defaults={"channel": channel},
    )
    job.mark_running(task_id=self.request.id)

    try:
        agent = build_script_agent(channel, topic)
        asyncio.run(
            Runner.run(
                agent,
                input=f"Write a full script for: {topic.title_idea}",
                max_turns=30,
            )
        )
        job.mark_completed()

        # Update PipelineRun to link the script job
        PipelineRun.objects.filter(id=pipeline_run_id).update(script_job=job)

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


# ── Asset Generation ─────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue="default")
def run_asset_job(self, script_job_id: str, pipeline_run_id: str) -> None:
    """Build AssetAgent and run it for the given script job."""
    import asyncio

    from agents import Runner
    from ***REMOVED***.agents.asset_agent import build_asset_agent
    from ***REMOVED***.assets.models import AssetJob
    from ***REMOVED***.pipeline.models import PipelineRun
    from ***REMOVED***.scripts.models import ScriptJob

    script_job = ScriptJob.objects.select_related("topic__channel").get(id=script_job_id)
    channel = script_job.topic.channel

    # Create AssetJob if not yet exists for this script job
    job, _ = AssetJob.objects.get_or_create(script_job=script_job)
    job.mark_running(task_id=self.request.id)

    try:
        agent = build_asset_agent(channel, script_job)
        asyncio.run(
            Runner.run(
                agent,
                input=f"Generate all assets for: {script_job.final_title or script_job.topic.title_idea}",
                max_turns=30,
            )
        )
        job.mark_completed()

        # Update PipelineRun to link the asset job
        PipelineRun.objects.filter(id=pipeline_run_id).update(asset_job=job)

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
    from ***REMOVED***.production.models import ProductionJob
    from ***REMOVED***.services.media.video import VideoRenderer

    job = ProductionJob.objects.select_related("asset_job__script_job__topic__channel").get(id=production_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        renderer = VideoRenderer(job)
        renderer.render()
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
    from ***REMOVED***.production.models import ProductionJob
    from ***REMOVED***.services.media.video import VideoQA

    job = ProductionJob.objects.get(id=production_job_id)
    qa = VideoQA(job)
    results = qa.run_all_checks()
    job.qa_results = results
    job.qa_passed = all(results.values())
    job.save(update_fields=["qa_results", "qa_passed", "updated_at"])

    if job.qa_passed:
        from ***REMOVED***.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(production_job=job)
        run.advance_to("UPLOADING")
        upload_video.delay(str(run.distribution_job.id))
    else:
        job.mark_paused(f"QA failed: {results}")


# ── Upload ───────────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=5, default_retry_delay=120, queue="uploads")
def upload_video(self, distribution_job_id: str) -> None:
    from ***REMOVED***.distribution.models import DistributionJob
    from ***REMOVED***.services.youtube.client import YouTubeClient

    job = DistributionJob.objects.select_related("channel", "production_job").get(id=distribution_job_id)
    job.mark_running(task_id=self.request.id)

    try:
        client = YouTubeClient.from_channel(job.channel)
        script_job = job.production_job.asset_job.script_job
        youtube_id = client.upload_video(
            video_path=str(job.production_job.final_video_path),
            title=script_job.final_title or script_job.topic.title_idea,
            description=script_job.video_description or "",
            tags=list(script_job.seo_tags or []),
            privacy_status="private",
        )
        job.youtube_video_id = youtube_id
        job.youtube_video_url = f"https://youtube.com/watch?v={youtube_id}"
        job.youtube_upload_status = "COMPLETED"
        job.published_at = timezone.now()
        job.save()

        # Mark job and pipeline run complete BEFORE dispatching post-upload chain
        job.mark_completed()

        from ***REMOVED***.pipeline.models import PipelineRun

        run = PipelineRun.objects.get(distribution_job=job)
        run.mark_published()
        run.save(update_fields=["overall_status", "current_stage", "completed_at", "updated_at"])

        # Chain post-upload tasks (fire-and-forget)
        (
            set_video_thumbnail.si(distribution_job_id)
            | post_pinned_comment.si(distribution_job_id)
            | add_to_playlist.si(distribution_job_id)
            | upload_youtube_short.si(distribution_job_id)
            | cross_post_social.si(distribution_job_id)
        ).delay()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


# ── Post-Upload Stubs ────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="uploads")
def set_video_thumbnail(self, distribution_job_id: str) -> None:
    """Upload selected thumbnail to YouTube. Stub — real implementation in Phase 8."""
    logger.info("set_video_thumbnail called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube thumbnail upload via YouTube Data API


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="uploads")
def post_pinned_comment(self, distribution_job_id: str) -> None:
    """Post pinned comment on the uploaded video. Stub — real implementation in Phase 8."""
    logger.info("post_pinned_comment called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube comment posting and pinning via YouTube Data API


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="uploads")
def add_to_playlist(self, distribution_job_id: str) -> None:
    """Add video to configured playlists. Stub — real implementation in Phase 8."""
    logger.info("add_to_playlist called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube playlist assignment via YouTube Data API


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="uploads")
def upload_youtube_short(self, distribution_job_id: str) -> None:
    """Upload the Shorts variant of the video. Stub — real implementation in Phase 8."""
    logger.info("upload_youtube_short called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Upload 9:16 cropped Shorts variant via YouTube Data API


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="uploads")
def cross_post_social(self, distribution_job_id: str) -> None:
    """Cross-post video clip to TikTok/Instagram/Twitter. Stub — real implementation in Phase 8."""
    logger.info("cross_post_social called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement cross-platform posting (TikTok, Instagram Reels, Twitter/X)


# ── Analytics ────────────────────────────────────────────────────────────────


@shared_task(queue="analytics")
def sync_channel_analytics(channel_id: str) -> None:
    """Pull analytics for all published videos on a channel."""
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.distribution.models import DistributionJob
    from ***REMOVED***.services.youtube.client import YouTubeClient

    channel = Channel.objects.get(id=channel_id)
    client = YouTubeClient.from_channel(channel)

    published_jobs = DistributionJob.objects.filter(
        channel=channel,
        status="COMPLETED",
        youtube_video_id__isnull=False,
    )

    for job in published_jobs:
        days_since = (timezone.now() - job.published_at).days
        for snapshot_day in [1, 7, 30]:
            if days_since >= snapshot_day:
                _create_or_update_snapshot(client, job, snapshot_day)


# ── Scheduled Tasks (via celery beat) ───────────────────────────────────────


@shared_task(queue="orchestration")
def daily_pipeline_trigger() -> None:
    """Runs every day at 6AM — checks each active channel and triggers pipelines."""
    from ***REMOVED***.channels.choices import ChannelStatus
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.pipeline.services import PipelineService

    for channel in Channel.objects.filter(status=ChannelStatus.ACTIVE):
        service = PipelineService(channel)
        service.trigger_daily_batch()


@shared_task(queue="analytics")
def weekly_analytics_sync() -> None:
    from ***REMOVED***.channels.choices import ChannelStatus
    from ***REMOVED***.channels.models import Channel

    for channel in Channel.objects.filter(status=ChannelStatus.ACTIVE):
        sync_channel_analytics.delay(str(channel.id))


# ── Helper Functions ─────────────────────────────────────────────────────────


def _save_research_results(job: Any, result: Any, channel: Any) -> None:
    """Parse agent output and bulk-create TopicIdea records.

    Args:
        job: ResearchJob instance
        result: RunResult from Runner.run()
        channel: Channel instance
    """
    import re

    from pydantic import TypeAdapter
    from pydantic import ValidationError

    from ***REMOVED***.agents.schemas import ResearchAgentOutput
    from ***REMOVED***.agents.schemas import ResearchTopicIdea
    from ***REMOVED***.research.choices import CompetitionLevel
    from ***REMOVED***.research.choices import TrendDirection
    from ***REMOVED***.research.models import TopicIdea

    raw: str = result.final_output or ""

    try:
        output = ResearchAgentOutput.model_validate_json(raw)
    except ValidationError:
        # Agent may return a bare JSON array — try to extract it
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            ta = TypeAdapter(list[ResearchTopicIdea])
            topics_list = ta.validate_json(match.group())
            output = ResearchAgentOutput(topics=topics_list)
        else:
            logger.exception(
                "Failed to parse research agent output",
                extra={"research_job_id": str(job.id), "raw_output": raw[:500]},
            )
            raise

    comp_map: dict[str, str] = {
        "LOW": CompetitionLevel.LOW,
        "MEDIUM": CompetitionLevel.MEDIUM,
        "HIGH": CompetitionLevel.HIGH,
    }
    trend_map: dict[str, str] = {
        "RISING": TrendDirection.RISING,
        "STABLE": TrendDirection.STABLE,
        "DECLINING": TrendDirection.DECLINING,
    }

    topic_objects = [
        TopicIdea(
            research_job=job,
            channel=channel,
            title_idea=t.title_idea,
            description=t.why_it_works,
            angle=t.hook_angle,
            keywords=[t.target_keyword],
            estimated_search_volume=t.estimated_search_vol,
            competition_level=comp_map.get(t.competition_level, CompetitionLevel.MEDIUM),
            trend_score=t.opportunity_score / 100.0,
            gap_opportunity_score=t.opportunity_score / 100.0,
            trend_direction=trend_map.get(t.trend_direction, TrendDirection.STABLE),
            thumbnail_concept=t.thumbnail_concept,
            why_it_works=t.why_it_works,
        )
        for t in output.topics
    ]

    created = TopicIdea.objects.bulk_create(topic_objects)
    logger.info(
        "Research results saved",
        extra={
            "research_job_id": str(job.id),
            "channel_slug": channel.slug,
            "topics_created": len(created),
            "research_summary": output.research_summary[:200],
        },
    )


def _create_or_update_snapshot(client: YouTubeClient, job: Any, snapshot_day: int) -> None:
    """Create or update analytics snapshot for a distribution job.

    Args:
        client: YouTubeAnalyticsClient instance
        job: DistributionJob instance
        snapshot_day: Number of days since publication (1, 7, or 30)

    TODO: Implement actual analytics data fetching from YouTube Analytics API.
    """
    from ***REMOVED***.distribution.models import AnalyticsSnapshot

    logger.warning("_create_or_update_snapshot called (placeholder) - job=%s, snapshot_day=%d", job.id, snapshot_day)

    # Placeholder: Create or update snapshot with mock data using correct field names
    AnalyticsSnapshot.objects.update_or_create(
        distribution_job=job,
        snapshot_days_after=snapshot_day,
        defaults={
            "channel": job.channel,
            "views": 1000 * snapshot_day,
            "likes": 50 * snapshot_day,
            "comments": 10 * snapshot_day,
            "shares": 5 * snapshot_day,
            "watch_time_hrs": float(500 * snapshot_day) / 60.0,
            "ctr_percent": 0.08,
            "avg_view_percentage": 0.65,
        },
    )
