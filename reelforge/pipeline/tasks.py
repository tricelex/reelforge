from __future__ import annotations

from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from dependency_injector.wiring import Provide
from dependency_injector.wiring import inject
from django.utils import timezone

from reelforge.agents.containers import AgentContainer

if TYPE_CHECKING:
    from reelforge.agents.providers.protocols import CommunitySearchProvider
    from reelforge.agents.providers.protocols import LLMProvider
    from reelforge.agents.providers.protocols import TrendsProvider
    from reelforge.agents.providers.protocols import VideoSearchProvider
    from reelforge.agents.providers.protocols import WebSearchProvider
    from reelforge.services.youtube.client import YouTubeClient  # used by upload/analytics tasks below

logger = get_task_logger(__name__)

# GPT-4o pricing (per 1M tokens) — used to estimate cost per research run
_GPT4O_INPUT_COST_PER_M = Decimal("2.50")
_GPT4O_OUTPUT_COST_PER_M = Decimal("10.00")
_SIX_PLACES = Decimal("0.000001")


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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    queue="research",
    soft_time_limit=1800,
    time_limit=2400,
)
@inject
def run_research_job(
    self: Any,
    channel_id: str,
    research_job_id: str,
    video_search: VideoSearchProvider = Provide[AgentContainer.video_search],
    trends: TrendsProvider = Provide[AgentContainer.trends],
    community: CommunitySearchProvider = Provide[AgentContainer.community],
    web_search: WebSearchProvider = Provide[AgentContainer.web_search],
) -> None:
    import asyncio

    from agents import Runner
    from reelforge.agents.research_agent import build_research_agent
    from reelforge.channels.models import Channel
    from reelforge.research.models import ResearchJob

    try:
        job = ResearchJob.objects.get(id=research_job_id)
    except ResearchJob.DoesNotExist:
        logger.exception(
            "ResearchJob %s not found — aborting task (will not retry)",
            research_job_id,
            extra={"research_job_id": research_job_id},
        )
        return

    job.mark_running(task_id=self.request.id)

    try:
        channel = Channel.objects.prefetch_related("competitors").get(id=channel_id)

        agent = build_research_agent(channel, video_search, trends, community, web_search)
        result = asyncio.run(
            Runner.run(
                agent,
                input=f"Research topics for channel {channel.name}. Niches: {channel.target_niches}",
                max_turns=50,
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
    from reelforge.channels.models import Channel
    from reelforge.research.choices import ResearchTrigger
    from reelforge.research.models import ResearchJob

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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    queue="default",
    soft_time_limit=1200,
    time_limit=1800,
)
@inject
def run_script_job(
    self: Any,
    topic_id: str,
    pipeline_run_id: str,
    web_search: WebSearchProvider = Provide[AgentContainer.web_search],
    llm: LLMProvider = Provide[AgentContainer.llm_openai],
) -> None:
    """Build ScriptAgent and run it for the given topic."""
    import asyncio

    from agents import Runner
    from reelforge.agents.script_agent import build_script_agent
    from reelforge.pipeline.models import PipelineRun
    from reelforge.research.models import TopicIdea
    from reelforge.scripts.models import ScriptJob

    topic = TopicIdea.objects.select_related("channel").get(id=topic_id)
    channel = topic.channel

    # Create ScriptJob if not yet exists for this topic
    job, _ = ScriptJob.objects.get_or_create(
        topic=topic,
        defaults={"channel": channel},
    )
    job.mark_running(task_id=self.request.id)

    try:
        agent = build_script_agent(channel, topic, web_search, llm)
        result = asyncio.run(
            Runner.run(
                agent,
                input=f"Write a full script for: {topic.title_idea}",
                max_turns=12,
            )
        )
        _save_script_results(job, result)
        job.mark_completed()

        # Update PipelineRun to link the script job
        PipelineRun.objects.filter(id=pipeline_run_id).update(script_job=job)

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc) from None


# ── Asset Generation ─────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    queue="default",
    soft_time_limit=1800,
    time_limit=2400,
)
def run_asset_job(self, script_job_id: str, pipeline_run_id: str) -> None:
    """Build AssetAgent and run it for the given script job."""
    import asyncio

    from agents import Runner
    from reelforge.agents.asset_agent import build_asset_agent
    from reelforge.assets.models import AssetJob
    from reelforge.pipeline.models import PipelineRun
    from reelforge.scripts.models import ScriptJob

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
    from reelforge.production.models import ProductionJob
    from reelforge.services.media.video import VideoRenderer

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
    from reelforge.services.youtube.client import YouTubeClient

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

        from reelforge.pipeline.models import PipelineRun

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
    from reelforge.channels.models import Channel
    from reelforge.distribution.models import DistributionJob
    from reelforge.services.youtube.client import YouTubeClient

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
    from reelforge.channels.choices import ChannelStatus
    from reelforge.channels.models import Channel
    from reelforge.pipeline.services import PipelineService

    for channel in Channel.objects.filter(status=ChannelStatus.ACTIVE):
        service = PipelineService(channel)
        service.trigger_daily_batch()


@shared_task(queue="analytics")
def weekly_analytics_sync() -> None:
    from reelforge.channels.choices import ChannelStatus
    from reelforge.channels.models import Channel

    for channel in Channel.objects.filter(status=ChannelStatus.ACTIVE):
        sync_channel_analytics.delay(str(channel.id))


# ── Helper Functions ─────────────────────────────────────────────────────────


def _save_research_results(job: Any, result: Any, channel: Any) -> None:
    """Parse agent output and bulk-create TopicIdea records, then write back
    token usage, cost, and raw data snapshots to the ResearchJob.

    Args:
        job: ResearchJob instance
        result: RunResult from Runner.run()
        channel: Channel instance
    """
    from reelforge.agents.schemas import ResearchAgentOutput
    from reelforge.research.choices import CompetitionLevel
    from reelforge.research.choices import TrendDirection
    from reelforge.research.models import TopicIdea

    if isinstance(result.final_output, ResearchAgentOutput):
        # output_type was set — SDK already validated and deserialized
        output = result.final_output
    else:
        # Fallback: raw string (e.g. agent ran without output_type)
        raw: str = result.final_output or ""
        try:
            output = ResearchAgentOutput.model_validate_json(raw)
        except Exception:
            logger.exception(
                "Failed to parse research agent output",
                extra={"research_job_id": str(job.id), "raw_output": raw[:500]},
            )
            raise

    # ── Token usage and cost ─────────────────────────────────────────────────
    total_input = sum(r.usage.input_tokens for r in result.raw_responses)
    total_output = sum(r.usage.output_tokens for r in result.raw_responses)
    total_tokens = total_input + total_output

    cost_usd = (
        Decimal(str(total_input)) * _GPT4O_INPUT_COST_PER_M / Decimal(1000000)
        + Decimal(str(total_output)) * _GPT4O_OUTPUT_COST_PER_M / Decimal(1000000)
    ).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)

    agent_run_id = result.last_response_id or ""

    # ── Raw data snapshots ────────────────────────────────────────────────────
    trend_data_raw: dict[str, Any] = {
        "youtube_results": [
            {
                "title_idea": t.title_idea,
                "keyword": t.target_keyword,
                "trend_direction": t.trend_direction,
                "opportunity_score": t.opportunity_score,
            }
            for t in output.topics
        ],
        "data_gaps": output.data_gaps,
        "collected_at": timezone.now().isoformat(),
    }

    competitor_data_raw: dict[str, Any] = {
        "channels": {
            dc.youtube_channel_id: {
                "channel_name": dc.channel_name,
                "channel_url": dc.channel_url,
                "subscriber_count": dc.subscriber_count,
                "notes": dc.notes,
            }
            for dc in output.discovered_competitors
        },
        "analyzed_at": timezone.now().isoformat(),
    }

    gap_analysis_raw: dict[str, Any] = {
        "opportunities": [
            {
                "title_idea": t.title_idea,
                "target_keyword": t.target_keyword,
                "opportunity_score": t.opportunity_score,
                "competition_level": t.competition_level,
                "content_format": t.content_format,
                "source_signals": t.source_signals,
            }
            for t in output.topics
        ],
        "coverage_gaps": [t.title_idea for t in output.topics if "competitor_gap_step4" in t.source_signals],
        "research_summary": output.research_summary,
        "analyzed_at": timezone.now().isoformat(),
    }

    # ── TopicIdea bulk_create ─────────────────────────────────────────────────
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

    per_topic_cost = (
        (cost_usd / len(output.topics)).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP) if output.topics else Decimal(0)
    )

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
            agent_run_id=agent_run_id,
            agent_tokens_used=total_tokens,
            agent_cost_usd=per_topic_cost,
            notes=("Sourced from: " + ", ".join(t.source_signals)) if t.source_signals else "",
        )
        for t in output.topics
    ]

    created = TopicIdea.objects.bulk_create(topic_objects)

    # ── Upsert competitors ────────────────────────────────────────────────────
    from reelforge.channels.models import ChannelCompetitor

    competitor_records = []
    for dc in output.discovered_competitors:
        channel_id = dc.youtube_channel_id or dc.channel_name
        if not channel_id:
            logger.warning(
                "Skipping discovered competitor with no identifier",
                extra={"research_job_id": str(job.id)},
            )
            continue
        if not dc.youtube_channel_id:
            logger.warning(
                "Discovered competitor missing youtube_channel_id; falling back to channel_name",
                extra={"channel_name": dc.channel_name, "research_job_id": str(job.id)},
            )
        obj, _ = ChannelCompetitor.objects.update_or_create(
            channel=channel,
            youtube_channel_id=channel_id,
            defaults={
                "channel_name": dc.channel_name,
                "channel_url": dc.channel_url,
                "subscriber_count": dc.subscriber_count,
                "notes": dc.notes,
                "last_analyzed": timezone.now(),
            },
        )
        competitor_records.append(obj)

    if competitor_records:
        job.competitors_analyzed.set(competitor_records)

    # ── Write back to ResearchJob ─────────────────────────────────────────────
    job.topics_discovered = len(created)
    job.notes = output.research_summary
    job.agent_run_id = agent_run_id
    job.agent_tokens_used = total_tokens
    job.agent_cost_usd = cost_usd
    job.trend_data_raw = trend_data_raw
    job.competitor_data_raw = competitor_data_raw
    job.gap_analysis_raw = gap_analysis_raw
    job.save(
        update_fields=[
            "topics_discovered",
            "notes",
            "agent_run_id",
            "agent_tokens_used",
            "agent_cost_usd",
            "trend_data_raw",
            "competitor_data_raw",
            "gap_analysis_raw",
            "updated_at",
        ]
    )

    logger.info(
        "Research results saved",
        extra={
            "research_job_id": str(job.id),
            "channel_slug": channel.slug,
            "topics_created": len(created),
            "competitors_created": len(competitor_records),
            "agent_tokens_used": total_tokens,
            "agent_cost_usd": str(cost_usd),
            "research_summary": output.research_summary[:200],
        },
    )


def _save_script_results(job: Any, result: Any) -> None:
    """Parse the ScriptAgent RunResult and persist all output fields to ScriptJob.

    Args:
        job: ScriptJob instance
        result: RunResult from Runner.run()
    """
    from reelforge.agents.schemas import ScriptAgentOutput

    if isinstance(result.final_output, ScriptAgentOutput):
        output = result.final_output
    else:
        raw: str = result.final_output or ""
        try:
            output = ScriptAgentOutput.model_validate_json(raw)
        except Exception:
            logger.exception(
                "Failed to parse ScriptAgent output",
                extra={"script_job_id": str(job.id), "raw_output": raw[:500]},
            )
            raise

    seo = output.seo_metadata

    # Convert AgentBRollSuggestion → stored BRollSuggestion format
    broll = [
        {
            "scene_index": b.scene_index,
            "section": b.section,
            "description": b.description,
            "stock_search_keywords": b.stock_search_keywords,
            "duration_seconds": b.duration_seconds,
            "visual_type": b.visual_type,
            "mood": b.mood,
            "fallback_description": b.fallback_description,
        }
        for b in output.broll_suggestions
    ]

    # Convert ScriptSection → stored format
    sections = [
        {
            "tag": s.tag,
            "content": s.content,
            "word_count": s.word_count,
            "estimated_duration_seconds": s.estimated_duration_seconds,
            "narrator_pacing": s.narrator_pacing,
            "narrator_notes": s.narrator_notes,
            "broll_indices": s.broll_indices,
        }
        for s in output.sections
    ]

    # Convert ResearchSource → stored format
    research_sources = [{"url": r.url, "title": r.title, "key_claim": r.key_claim} for r in output.research_sources]

    # Convert chapters: ScriptChapter(time, label) → Chapter(timestamp, title)
    chapters = [{"timestamp": c.time, "title": c.label} for c in seo.chapters]

    # Store hook_used as a generated_hooks entry with score from quality_flags
    generated_hooks: list[dict[str, Any]] = []
    if output.hook_used:
        hook_type = output.quality_flags.hook_type or "statement"
        generated_hooks = [{"text": output.hook_used, "type": hook_type, "score": output.hook_score}]

    # Quality flags dict
    qf = output.quality_flags
    quality_flags: dict[str, Any] = {
        "hook_score": qf.hook_score,
        "hook_type": qf.hook_type,
        "avg_sentence_length": qf.avg_sentence_length,
        "passive_voice_instances": qf.passive_voice_instances,
        "jargon_flags": qf.jargon_flags,
        "faceless_compliance": qf.faceless_compliance,
        "research_confidence": qf.research_confidence,
    }

    job.script_text = output.script_text
    job.sections = sections
    job.word_count = output.word_count
    job.estimated_duration_mins = output.estimated_duration_mins
    job.broll_suggestions = broll
    job.research_sources = research_sources
    job.hook_score = output.hook_score
    job.generated_hooks = generated_hooks
    job.quality_flags = quality_flags
    job.ready_for_production = output.ready_for_production
    job.revision_notes = output.revision_notes
    job.final_title = seo.final_title
    job.final_description = seo.description
    job.seo_tags = seo.tags
    job.chapters = chapters
    job.pinned_comment = seo.pinned_comment
    job.thumbnail_text = seo.thumbnail_text
    job.thumbnail_emotion = seo.thumbnail_emotion
    job.search_hashtags = list(seo.search_hashtags)

    job.save(
        update_fields=[
            "script_text",
            "sections",
            "word_count",
            "estimated_duration_mins",
            "broll_suggestions",
            "research_sources",
            "hook_score",
            "generated_hooks",
            "quality_flags",
            "ready_for_production",
            "revision_notes",
            "final_title",
            "final_description",
            "seo_tags",
            "chapters",
            "pinned_comment",
            "thumbnail_text",
            "thumbnail_emotion",
            "search_hashtags",
            "updated_at",
        ]
    )

    # Auto-create version 1 revision — replaces save_script_draft tool call
    from reelforge.scripts.models import ScriptRevision

    ScriptRevision.objects.create(
        script_job=job,
        version_number=1,
        script_text=output.script_text,
        word_count=output.word_count,
        change_summary="Agent v1 — auto-saved from pipeline",
    )

    logger.info(
        "Script results saved to ScriptJob",
        extra={
            "script_job_id": str(job.id),
            "word_count": job.word_count,
            "final_title": job.final_title,
            "broll_count": len(broll),
            "ready_for_production": output.ready_for_production,
            "hook_score": output.hook_score,
            "research_sources_count": len(research_sources),
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
    from reelforge.distribution.models import AnalyticsSnapshot

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
