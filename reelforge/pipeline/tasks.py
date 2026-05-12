from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from dependency_injector.wiring import Provide
from dependency_injector.wiring import inject
from django.utils import timezone

from ***REMOVED***.agents.containers import AgentContainer

if TYPE_CHECKING:
    from ***REMOVED***.agents.providers.protocols import LLMProvider
    from ***REMOVED***.agents.providers.protocols import WebSearchProvider
    from ***REMOVED***.ai.schemas.research import ResearchAgentOutput
    from ***REMOVED***.services.youtube.client import YouTubeClient  # used by upload/analytics tasks below

logger = get_task_logger(__name__)

# GPT-4o pricing (per 1M tokens) — used to estimate cost per research run
_GPT4O_INPUT_COST_PER_M = Decimal("2.50")
_GPT4O_OUTPUT_COST_PER_M = Decimal("10.00")
_SIX_PLACES = Decimal("0.000001")


# ── Research ────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    queue="research",
    soft_time_limit=1800,
    time_limit=2400,
)
def run_research_job(
    self: Any,
    channel_id: str,
    research_job_id: str,
) -> None:
    from django.conf import settings

    from ***REMOVED***.ai.agents.research import research_agent
    from ***REMOVED***.ai.deps import ResearchDeps
    from ***REMOVED***.ai.providers.serpapi import get_community
    from ***REMOVED***.ai.providers.serpapi import get_trends
    from ***REMOVED***.ai.providers.serpapi import get_youtube_search
    from ***REMOVED***.ai.providers.tavily import get_web_search
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.models import ResearchJob

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

        deps = ResearchDeps(
            video_search=get_youtube_search(),
            web_search=get_web_search(),
            trends=get_trends(),
            community=get_community(),
            channel=channel,
        )
        result = research_agent.run_sync(
            f"Research topics for channel {channel.name}. Niches: {channel.target_niches}",
            deps=deps,
            model=settings.RESEARCH_AGENT_MODEL,
        )
        _save_research_results(job, result, channel)
        job.mark_completed()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise


@shared_task(bind=True, queue="research")
def run_research_job_for_channel(self, channel_id: str) -> None:  # noqa: ANN001, ARG001
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
    except Exception:
        logger.exception("Failed to create research job for channel %s", channel_id)
        raise


# ── Script Generation ────────────────────────────────────────────────────────


@shared_task(
    bind=True,
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
        raise


# ── Script Revision ──────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    queue="default",
    soft_time_limit=1200,
    time_limit=1800,
)
@inject
def run_script_revision_job(
    self: Any,
    script_job_id: str,
    web_search: WebSearchProvider = Provide[AgentContainer.web_search],
    llm: LLMProvider = Provide[AgentContainer.llm_openai],
) -> None:
    """Re-run the ScriptAgent on an existing ScriptJob to incorporate a change request.
    Reads script_job.change_request, passes existing script + request to agent,
    updates ScriptJob fields, and creates a new ScriptRevision.
    """
    import asyncio

    from agents import Runner
    from ***REMOVED***.agents.script_agent import build_script_agent
    from ***REMOVED***.scripts.models import ScriptJob

    script_job = ScriptJob.objects.select_related("topic__channel").get(id=script_job_id)
    channel = script_job.topic.channel
    topic = script_job.topic
    change_request = script_job.change_request

    # Operator-triggered revision: use begin_revision so the retry budget is not
    # consulted. Guard against the already-RUNNING case (Celery retry race: a previous
    # attempt transitioned to RUNNING before failing, so the retry finds it there).
    from django_fsm import can_proceed

    if can_proceed(script_job.begin_revision):
        script_job.begin_revision(task_id=self.request.id)
        script_job.save(update_fields=["status", "started_at", "celery_task_id"])
    else:
        # Already RUNNING from a prior attempt — just re-stamp the task ID.
        script_job.celery_task_id = self.request.id
        script_job.save(update_fields=["celery_task_id"])

    try:
        # Compute next version number before saving (avoids unique-constraint clash)
        last_revision = script_job.revisions.order_by("-version_number").first()
        next_version = (last_revision.version_number + 1) if last_revision else 2

        agent = build_script_agent(channel, topic, web_search, llm)
        hook_text = script_job.selected_hook.text if script_job.selected_hook else ""
        revision_input = (
            f"Revise the existing script for: {topic.title_idea}\n\n"
            f"CHANGE REQUEST FROM OPERATOR:\n{change_request}\n\n"
            f"EXISTING SCRIPT:\n{script_job.script_text}\n\n"
            f"HOOK USED (score {script_job.hook_score:.1f}):\n"
            f"{hook_text}\n\n"
            f"AGENT SELF-REVIEW NOTES FROM PREVIOUS RUN:\n{script_job.revision_notes or '(none)'}\n\n"
            "Incorporate the change request. Keep what works well. "
            "Return the complete refined script via the standard output format."
        )
        result = asyncio.run(Runner.run(agent, input=revision_input, max_turns=12))

        _save_script_results(
            script_job,
            result,
            version_number=next_version,
            change_summary=f"Revision: {change_request[:200]}",
        )
        script_job.mark_completed()

        # Clear the change_request after successful processing
        script_job.change_request = ""
        script_job.save(update_fields=["change_request", "updated_at"])

    except Exception as exc:
        script_job.mark_failed(str(exc))
        raise


# ── Asset Generation ─────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    queue="default",
    soft_time_limit=1800,
    time_limit=2400,
)
def run_asset_job(self, script_job_id: str, pipeline_run_id: str) -> None:  # noqa: ANN001
    """Coordinate asset generation — creates Run records and dispatches sub-tasks.

    Voiceover, image generation, and thumbnail generation run in parallel.
    Each sub-task auto-selects itself as the active run if none is set yet.
    """
    from django.db import transaction
    from django.db.models import Max

    from ***REMOVED***.assets.models import AssetJob
    from ***REMOVED***.assets.models import ImageGenerationRun
    from ***REMOVED***.assets.models import ThumbnailRun
    from ***REMOVED***.assets.models import VoiceoverRun
    from ***REMOVED***.pipeline.models import PipelineRun
    from ***REMOVED***.scripts.models import ScriptJob

    script_job = ScriptJob.objects.select_related("topic__channel").get(id=script_job_id)

    # Create AssetJob if not yet exists for this script job
    job, _ = AssetJob.objects.get_or_create(script_job=script_job)
    job.mark_running(task_id=self.request.id)

    try:
        # Determine the next run number for each sub-type
        next_vo_run = (job.voiceover_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
        next_img_run = (job.image_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
        next_thumb_run = (job.thumbnail_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1

        voiceover_run = VoiceoverRun.objects.create(asset_job=job, run_number=next_vo_run)
        image_run = ImageGenerationRun.objects.create(asset_job=job, run_number=next_img_run)
        thumbnail_run = ThumbnailRun.objects.create(asset_job=job, run_number=next_thumb_run)

        # Dispatch sub-tasks in parallel after commit
        def _dispatch() -> None:
            run_voiceover_run.delay(str(voiceover_run.id))
            run_image_generation_run.delay(str(image_run.id))
            run_thumbnail_run.delay(str(thumbnail_run.id))

        transaction.on_commit(_dispatch)

        # Update PipelineRun to link the asset job
        PipelineRun.objects.filter(id=pipeline_run_id).update(asset_job=job)

    except Exception as exc:
        job.mark_failed(str(exc))
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_scene_breakdown_job",
    queue="default",
    soft_time_limit=360,
    time_limit=420,
    max_retries=2,
    default_retry_delay=120,
)
def run_scene_breakdown_job(self, scene_breakdown_job_id: str, pipeline_run_id: str | None = None) -> None:  # noqa: ANN001, PLR0915
    """Run scene breakdown for a script — splits script into timed scene dicts.

    When called from the pipeline (pipeline_run_id provided), automatically transitions
    the PipelineRun to GENERATING_ASSETS and dispatches run_asset_job upon completion.
    """
    from ***REMOVED***.production.models import SceneBreakdownJob

    try:
        job = SceneBreakdownJob.objects.select_related(
            "script_job__topic__channel",
        ).get(id=scene_breakdown_job_id)
    except SceneBreakdownJob.DoesNotExist:
        logger.error(  # noqa: TRY400
            "SceneBreakdownJob %s not found — aborting",
            scene_breakdown_job_id,
            extra={"scene_breakdown_job_id": scene_breakdown_job_id},
        )
        return

    job.mark_running(task_id=self.request.id)

    try:
        from agents import Runner
        from ***REMOVED***.agents.schemas import VisualPlannerOutput  # noqa: TC001
        from ***REMOVED***.agents.visual_planner import build_visual_planner_agent

        sections = job.script_job.sections or []
        broll_suggestions = job.script_job.broll_suggestions or []

        # Authoritative duration: estimated_duration_mins → word count fallback
        total_duration_seconds: float = float(job.script_job.estimated_duration_mins or 0) * 60.0
        if not total_duration_seconds:
            word_count = job.script_job.word_count or len(
                (job.script_job.script_text or "").split()
            )
            total_duration_seconds = (word_count / 130.0) * 60.0
        _MIN_DURATION_SECONDS = 30  # noqa: N806
        if total_duration_seconds < _MIN_DURATION_SECONDS:
            msg = (
                f"total_duration_seconds={total_duration_seconds:.1f} is suspiciously short. "
                "Check estimated_duration_mins or script word count."
            )
            raise ValueError(msg)  # noqa: TRY301

        channel = job.script_job.topic.channel
        narrative_mode: str = getattr(job.script_job, "narrative_mode", "") or "REVEAL"

        logger.info(
            "VisualPlannerAgent: planning timeline",
            extra={
                "scene_breakdown_job_id": scene_breakdown_job_id,
                "total_duration_seconds": total_duration_seconds,
                "sections": len(sections),
                "broll_suggestions": len(broll_suggestions),
            },
        )

        agent = build_visual_planner_agent(
            sections=sections,
            broll_suggestions=broll_suggestions,
            total_duration_seconds=total_duration_seconds,
            channel_tone=channel.content_tone or "informative",
            narrative_mode=narrative_mode,
        )

        result = Runner.run_sync(agent, input="Generate the complete visual timeline.", max_turns=1)
        planner_output: VisualPlannerOutput = result.final_output

        scenes = [
            {
                # Legacy fields (downstream asset job compatibility)
                "scene_id": seg.scene_id,
                "section_tag": seg.section_tag,
                "narration": seg.narration_excerpt,
                "duration_estimate": seg.duration,
                "visual_keywords": seg.visual_keywords,
                "mood": seg.mood,
                "caption_text": seg.narration_excerpt[:100],
                "animation_type": seg.animation_type,
                "image_prompt": seg.image_prompt,
                "image_style_preset": seg.style_preset,
                "broll_indices": [],
                # New timing and animation fields
                "start_seconds": seg.start_seconds,
                "end_seconds": seg.end_seconds,
                "colour_palette": seg.colour_palette,
                "video_prompt": seg.video_prompt,
                "is_transition": seg.is_transition,
            }
            for seg in planner_output.segments
        ]

        job.scenes = scenes
        job.scene_count = len(scenes)
        job.total_estimated_duration = planner_output.total_duration_seconds
        job.breakdown_provider = "gpt-5.2"
        job.save(update_fields=[
            "scenes", "scene_count", "total_estimated_duration",
            "breakdown_provider", "updated_at",
        ])
        job.mark_completed()

        logger.info(
            "VisualPlannerAgent complete",
            extra={
                "scene_breakdown_job_id": str(job.id),
                "scene_count": job.scene_count,
                "total_duration": job.total_estimated_duration,
                "coverage_confirmed": planner_output.coverage_confirmed,
                "revision_notes": planner_output.revision_notes,
            },
        )

        # If called from the pipeline, chain to asset generation
        if pipeline_run_id:
            from django.db import transaction as db_transaction
            from django_fsm import can_proceed

            from ***REMOVED***.pipeline.choices import PipelineStatus
            from ***REMOVED***.pipeline.models import PipelineRun

            pipeline_run = PipelineRun.objects.select_related("script_job").get(id=pipeline_run_id)
            if can_proceed(pipeline_run.begin_assets):
                pipeline_run.begin_assets()
                pipeline_run.save()
                script_job_id = str(pipeline_run.script_job_id)
                rid = pipeline_run_id
                db_transaction.on_commit(lambda sjid=script_job_id, rid=rid: run_asset_job.delay(sjid, rid))
                logger.info(
                    "Scene breakdown complete — advancing to asset generation",
                    extra={
                        "pipeline_run_id": pipeline_run_id,
                        "scene_breakdown_job_id": scene_breakdown_job_id,
                    },
                )
            elif pipeline_run.overall_status == PipelineStatus.GENERATING_ASSETS:
                # Re-dispatch case: run already in GENERATING_ASSETS (e.g. operator re-ran scene breakdown)
                # Skip FSM transition and fire asset job directly
                script_job_id = str(pipeline_run.script_job_id)
                rid = pipeline_run_id
                db_transaction.on_commit(lambda sjid=script_job_id, rid=rid: run_asset_job.delay(sjid, rid))
                logger.info(
                    "Scene breakdown complete — run already in GENERATING_ASSETS, re-dispatching asset job",
                    extra={
                        "pipeline_run_id": pipeline_run_id,
                        "scene_breakdown_job_id": scene_breakdown_job_id,
                    },
                )
            else:
                logger.warning(
                    "Scene breakdown complete but cannot advance pipeline run to assets",
                    extra={
                        "pipeline_run_id": pipeline_run_id,
                        "status": pipeline_run.overall_status,
                    },
                )

    except Exception as exc:
        job.mark_failed(str(exc))
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_voiceover_run",
    queue="default",
    max_retries=3,
    soft_time_limit=1500,
    time_limit=1800,
)
def run_voiceover_run(self, voiceover_run_id: str) -> None:  # noqa: ANN001, PLR0915
    """Execute a single voiceover generation attempt.
    On completion, auto-selects this run on the parent AssetJob if none is selected.
    """
    from django.utils import timezone

    from ***REMOVED***.assets.models import VoiceoverRun

    try:
        run = VoiceoverRun.objects.select_related("asset_job__script_job__topic__channel").get(id=voiceover_run_id)
    except VoiceoverRun.DoesNotExist:
        logger.error(  # noqa: TRY400
            "VoiceoverRun %s not found — aborting",
            voiceover_run_id,
            extra={"voiceover_run_id": voiceover_run_id},
        )
        return

    run.status = "RUNNING"
    run.celery_task_id = self.request.id
    run.started_at = timezone.now()
    run.save(update_fields=["status", "celery_task_id", "started_at"])

    try:
        from decimal import Decimal
        from pathlib import Path

        from django.conf import settings

        from ***REMOVED***.assets.models import VoiceoverSegment
        from ***REMOVED***.core.storage import get_voiceover_full_path
        from ***REMOVED***.core.storage import get_voiceover_segment_path
        from ***REMOVED***.services.media.audio import AudioProcessor
        from ***REMOVED***.services.providers.registry import get_tts_provider

        media_root = Path(settings.MEDIA_ROOT)

        asset_job = run.asset_job
        script_job = asset_job.script_job
        channel = script_job.topic.channel
        segments = list(script_job.segments or [])

        if not segments:
            logger.warning(
                "VoiceoverRun: no TTS segments on script_job — completing with empty voiceover",
                extra={"voiceover_run_id": str(run.id), "script_job_id": str(script_job.id)},
            )
            run.status = "COMPLETED"
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "completed_at", "updated_at"])
            if not asset_job.selected_voiceover_run_id:
                asset_job.selected_voiceover_run = run
                asset_job.save(update_fields=["selected_voiceover_run", "updated_at"])
            return

        tts = get_tts_provider(channel)
        total_cost = Decimal(0)
        segment_files: list[dict] = []

        for seg in segments:
            seg_id = seg.get("segment_id", 0)
            text = seg.get("text", "").strip()
            if not text:
                continue

            tts_response = tts.synthesize(
                text=text,
                voice_id=channel.tts_voice_id or "default",
                stability=channel.tts_stability,
                similarity_boost=channel.tts_similarity,
                style=channel.tts_style,
            )

            audio_path = get_voiceover_segment_path(str(asset_job.id), seg_id)
            audio_path.write_bytes(tts_response.audio_bytes)

            VoiceoverSegment.objects.update_or_create(
                asset_job=asset_job,
                segment_id=seg_id,
                defaults={
                    "voiceover_run": run,
                    "text": text,
                    "section": seg.get("section", ""),
                    "audio_file": str(audio_path.relative_to(media_root)),
                    "duration_sec": tts_response.duration_sec,
                    "tts_provider_used": tts.name,
                    "voice_id_used": channel.tts_voice_id or "default",
                    "generation_cost_usd": Decimal(str(tts_response.cost_usd)),
                    "status": "COMPLETED",
                },
            )
            segment_files.append({"segment_id": seg_id, "path": str(audio_path)})
            total_cost += Decimal(str(tts_response.cost_usd))

        # Merge all segments into full voiceover
        processor = AudioProcessor()
        output_path = get_voiceover_full_path(str(asset_job.id))
        merge_result = processor.merge_voiceover_segments(
            segment_files=segment_files,
            output_path=str(output_path),
        )

        # Compute timing offsets and update start_ms/end_ms on each segment
        timings = processor.get_segment_timings(segment_files)
        timing_map = {t["segment_id"]: t for t in timings}
        for seg_obj in VoiceoverSegment.objects.filter(asset_job=asset_job, voiceover_run=run):
            timing = timing_map.get(seg_obj.segment_id)
            if timing:
                seg_obj.start_ms = timing["start_ms"]
                seg_obj.end_ms = timing["end_ms"]
                seg_obj.save(update_fields=["start_ms", "end_ms"])

        # Update run record
        run.merged_audio_file = str(output_path.relative_to(media_root))
        run.total_duration_sec = merge_result["duration_sec"]
        run.total_cost_usd = total_cost
        run.provider = tts.name
        run.voice_id = channel.tts_voice_id or "default"
        run.status = "COMPLETED"
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "merged_audio_file",
                "total_duration_sec",
                "total_cost_usd",
                "provider",
                "voice_id",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        # Auto-select if no run is currently selected
        if not asset_job.selected_voiceover_run_id:
            asset_job.selected_voiceover_run = run
            asset_job.save(update_fields=["selected_voiceover_run", "updated_at"])

        # Update scene breakdown durations based on actual TTS durations
        from ***REMOVED***.production.models import SceneBreakdownJob

        breakdown = SceneBreakdownJob.objects.filter(script_job=script_job).first()
        if breakdown and breakdown.scenes:
            timing_map = {t["segment_id"]: t for t in timings}
            updated = False
            for scene in breakdown.scenes:
                seg_id = scene.get("scene_id", 0)
                timing = timing_map.get(seg_id)
                if timing:
                    audio_dur = (timing["end_ms"] - timing["start_ms"]) / 1000.0
                    scene["duration_estimate"] = max(round(audio_dur + 1.5, 2), 6.0)
                    updated = True
            if updated:
                breakdown.total_estimated_duration = sum(s.get("duration_estimate", 8.0) for s in breakdown.scenes)
                breakdown.save(update_fields=["scenes", "total_estimated_duration", "updated_at"])

        logger.info(
            "VoiceoverRun complete",
            extra={
                "voiceover_run_id": str(run.id),
                "segments": len(segment_files),
                "duration_sec": merge_result["duration_sec"],
                "total_cost_usd": str(total_cost),
            },
        )

    except Exception as exc:
        import httpx

        if isinstance(exc, (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout)):
            logger.warning(
                "Transient network error in VoiceoverRun — retrying",
                extra={
                    "voiceover_run_id": voiceover_run_id,
                    "attempt": self.request.retries + 1,
                    "error": str(exc),
                },
            )
            raise self.retry(exc=exc, countdown=2**self.request.retries * 30)  # noqa: B904

        run.status = "FAILED"
        run.notes = str(exc)[:2000]
        run.save(update_fields=["status", "notes", "updated_at"])
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_image_generation_run",
    queue="default",
    soft_time_limit=750,
    time_limit=900,
)
def run_image_generation_run(self, image_generation_run_id: str) -> None:  # noqa: ANN001, PLR0915
    """Execute a single image generation attempt.
    On completion, auto-selects this run on the parent AssetJob if none is selected.
    """
    from django.utils import timezone

    from ***REMOVED***.assets.models import ImageGenerationRun

    try:
        run = ImageGenerationRun.objects.select_related("asset_job__script_job__topic__channel").get(
            id=image_generation_run_id
        )
    except ImageGenerationRun.DoesNotExist:
        logger.error(  # noqa: TRY400
            "ImageGenerationRun %s not found — aborting",
            image_generation_run_id,
            extra={"image_generation_run_id": image_generation_run_id},
        )
        return

    run.status = "RUNNING"
    run.celery_task_id = self.request.id
    run.started_at = timezone.now()
    run.save(update_fields=["status", "celery_task_id", "started_at"])

    try:
        from decimal import Decimal
        from pathlib import Path

        from django.conf import settings

        from ***REMOVED***.assets.models import GeneratedImage
        from ***REMOVED***.core.storage import get_image_path
        from ***REMOVED***.production.models import SceneBreakdownJob
        from ***REMOVED***.services.media.image_prompt import build_image_prompt
        from ***REMOVED***.services.providers.registry import get_image_provider

        media_root = Path(settings.MEDIA_ROOT)
        asset_job = run.asset_job
        script_job = asset_job.script_job
        channel = script_job.topic.channel

        # Prefer SceneBreakdownJob.scenes, fall back to broll_suggestions
        breakdown = SceneBreakdownJob.objects.filter(script_job=script_job).first()
        scenes: list[dict] = (breakdown.scenes or []) if breakdown else []

        if not scenes:
            broll_list = script_job.broll_suggestions or []
            scenes = [
                {
                    "scene_id": i + 1,
                    "section_tag": b.get("section", "SECTION_1"),
                    "image_prompt": build_image_prompt(b),
                    "duration_estimate": float(b.get("duration_seconds", 8)),
                    "mood": b.get("mood", "neutral"),
                    "animation_type": "body_concept",
                    "image_style_preset": b.get("style_preset", "cinematic_realism"),
                }
                for i, b in enumerate(broll_list)
            ]

        if not scenes:
            logger.warning(
                "ImageGenerationRun: no scenes or broll — completing with 0 images",
                extra={"image_generation_run_id": str(run.id)},
            )
            run.status = "COMPLETED"
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "completed_at", "updated_at"])
            if not asset_job.selected_image_run_id:
                asset_job.selected_image_run = run
                asset_job.save(update_fields=["selected_image_run", "updated_at"])
            return

        img_provider = get_image_provider(channel)
        total_cost = Decimal(0)
        images_count = 0

        # Build ordered list of (scene, scene_id, prompt), filtering out empty prompts
        valid_scenes: list[tuple[dict, int, str]] = []
        for i, scene in enumerate(scenes):
            scene_id = scene.get("scene_id", i + 1)
            prompt = scene.get("image_prompt", "") or scene.get("narration", "")[:300]
            if prompt:
                valid_scenes.append((scene, scene_id, prompt))

        scene_prompts = [{"prompt": p, "width": 1920, "height": 1080} for _, _, p in valid_scenes]
        results = asyncio.run(img_provider.generate_batch_async(scene_prompts))

        for (scene, scene_id, prompt), result in zip(valid_scenes, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning(
                    "Image generation failed for scene %d — skipping",
                    scene_id,
                    extra={"image_generation_run_id": str(run.id), "scene_id": scene_id, "error": str(result)},
                )
                continue

            img_data = result
            img_path = get_image_path(str(asset_job.id), scene_id)
            img_path.write_bytes(img_data.image_bytes)

            GeneratedImage.objects.update_or_create(
                asset_job=asset_job,
                position_idx=scene_id,
                defaults={
                    "image_run": run,
                    "prompt_used": prompt,
                    "image_file": str(img_path.relative_to(media_root)),
                    "provider": img_provider.name,
                    "section": scene.get("section_tag", ""),
                    "timestamp_approx": "",
                    "generation_cost_usd": Decimal(str(img_data.cost_usd)),
                    "is_selected": True,
                },
            )
            total_cost += Decimal(str(img_data.cost_usd))
            images_count += 1

        run.images_count = images_count
        run.total_cost_usd = total_cost
        run.provider = img_provider.name
        run.status = "COMPLETED"
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "images_count",
                "total_cost_usd",
                "provider",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        # Auto-select if no run is currently selected
        asset_job = run.asset_job
        if not asset_job.selected_image_run_id:
            asset_job.selected_image_run = run
            asset_job.save(update_fields=["selected_image_run", "updated_at"])

        logger.info(
            "ImageGenerationRun complete",
            extra={
                "image_generation_run_id": str(run.id),
                "images_count": images_count,
                "total_cost_usd": str(total_cost),
            },
        )

    except Exception as exc:
        run.status = "FAILED"
        run.notes = str(exc)[:2000]
        run.save(update_fields=["status", "notes", "updated_at"])
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_video_clip_generation_run",
    queue="rendering",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_video_clip_generation_run(self, video_clip_run_id: str) -> None:  # noqa: ANN001, PLR0915
    """Execute a single video clip generation attempt (animates still images).
    On completion, auto-selects this run on the parent AssetJob if none is selected.
    """
    from django.utils import timezone

    from ***REMOVED***.assets.models import VideoClipGenerationRun

    try:
        run = VideoClipGenerationRun.objects.select_related(
            "asset_job__script_job__topic__channel",
            "image_run",
        ).get(id=video_clip_run_id)
    except VideoClipGenerationRun.DoesNotExist:
        logger.error(  # noqa: TRY400
            "VideoClipGenerationRun %s not found — aborting",
            video_clip_run_id,
            extra={"video_clip_run_id": video_clip_run_id},
        )
        return

    run.status = "RUNNING"
    run.celery_task_id = self.request.id
    run.started_at = timezone.now()
    run.save(update_fields=["status", "celery_task_id", "started_at"])

    try:
        from decimal import Decimal
        from pathlib import Path

        from django.conf import settings

        from ***REMOVED***.assets.models import GeneratedImage
        from ***REMOVED***.assets.models import GeneratedVideoClip
        from ***REMOVED***.core.storage import get_clip_path
        from ***REMOVED***.production.models import SceneBreakdownJob
        from ***REMOVED***.services.providers.registry import get_video_clip_provider
        from ***REMOVED***.services.providers.video_clip.fal_ai import ANIMATION_PROMPTS

        media_root = Path(settings.MEDIA_ROOT)
        asset_job = run.asset_job
        script_job = asset_job.script_job
        channel = script_job.topic.channel
        image_run = run.image_run

        if not image_run or image_run.status != "COMPLETED":
            msg = f"ImageGenerationRun must be COMPLETED before animating clips (status={getattr(image_run, 'status', None)})"
            raise ValueError(msg)  # noqa: TRY301

        # Voiceover must be complete so scene breakdown has accurate durations
        voiceover_run = asset_job.selected_voiceover_run
        if not voiceover_run or voiceover_run.status != "COMPLETED":
            msg = "Selected VoiceoverRun must be COMPLETED before generating video clips"
            raise ValueError(msg)  # noqa: TRY301

        images = list(GeneratedImage.objects.filter(image_run=image_run).order_by("position_idx"))
        if not images:
            logger.warning(
                "VideoClipGenerationRun: image_run has no GeneratedImage records",
                extra={"video_clip_run_id": str(run.id), "image_run_id": str(image_run.id)},
            )
            run.status = "COMPLETED"
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "completed_at", "updated_at"])
            return

        # Load scene breakdown for animation types
        breakdown = SceneBreakdownJob.objects.filter(script_job=script_job).first()
        scenes_by_id: dict[int, dict] = {}
        if breakdown and breakdown.scenes:
            scenes_by_id = {s.get("scene_id", 0): s for s in breakdown.scenes}

        clip_provider = get_video_clip_provider(channel)
        total_cost = Decimal(0)
        clips_count = 0

        # Build ordered list of (img, anim_prompt, duration), filtering images with no file
        valid_clips: list[tuple[Any, str, float]] = []
        for img in images:
            img_path = img.image_file.path if img.image_file else ""
            if not img_path:
                logger.warning(
                    "GeneratedImage has no file — skipping clip",
                    extra={"image_id": str(img.id), "position_idx": img.position_idx},
                )
                continue
            scene = scenes_by_id.get(img.position_idx, {})
            animation_type = scene.get("animation_type", "body_concept")
            anim_prompt = ANIMATION_PROMPTS.get(animation_type, ANIMATION_PROMPTS["body_concept"])
            duration_estimate = float(scene.get("duration_estimate", 8.0))
            valid_clips.append((img, anim_prompt, duration_estimate))

        clip_requests = [
            {"image_path": img.image_file.path, "prompt": prompt, "duration_sec": dur}
            for img, prompt, dur in valid_clips
        ]
        clip_results = asyncio.run(clip_provider.generate_clips_async(clip_requests))

        for (img, anim_prompt, _), clip_result in zip(valid_clips, clip_results, strict=False):
            if isinstance(clip_result, BaseException):
                logger.warning(
                    "Video clip generation failed for image %d — skipping",
                    img.position_idx,
                    extra={"video_clip_run_id": str(run.id), "image_id": str(img.id), "error": str(clip_result)},
                )
                continue

            clip_path = get_clip_path(str(asset_job.id), img.position_idx)
            clip_path.write_bytes(clip_result.clip_bytes)

            GeneratedVideoClip.objects.update_or_create(
                video_clip_run=run,
                position_idx=img.position_idx,
                defaults={
                    "source_image": img,
                    "prompt_used": anim_prompt,
                    "clip_file": str(clip_path.relative_to(media_root)),
                    "duration_sec": clip_result.duration_sec,
                    "provider": clip_provider.name,
                    "is_selected": True,
                    "generation_cost_usd": Decimal(str(clip_result.cost_usd)),
                },
            )
            total_cost += Decimal(str(clip_result.cost_usd))
            clips_count += 1

        run.clips_count = clips_count
        run.total_cost_usd = total_cost
        run.provider = clip_provider.name
        run.status = "COMPLETED"
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "clips_count",
                "total_cost_usd",
                "provider",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        # Auto-select if no run is currently selected
        if not asset_job.selected_video_clip_run_id:
            asset_job.selected_video_clip_run = run
            asset_job.save(update_fields=["selected_video_clip_run", "updated_at"])

        logger.info(
            "VideoClipGenerationRun complete",
            extra={
                "video_clip_run_id": str(run.id),
                "clips_count": clips_count,
                "total_cost_usd": str(total_cost),
            },
        )

    except Exception as exc:
        run.status = "FAILED"
        run.notes = str(exc)[:2000]
        run.save(update_fields=["status", "notes", "updated_at"])
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_thumbnail_run",
    queue="default",
    soft_time_limit=480,
    time_limit=600,
)
def run_thumbnail_run(self, thumbnail_run_id: str) -> None:  # noqa: ANN001, PLR0915
    """Execute a single thumbnail generation attempt.
    On completion, auto-selects this run on the parent AssetJob if none is selected.
    """
    from django.utils import timezone

    from ***REMOVED***.assets.models import ThumbnailRun

    try:
        run = ThumbnailRun.objects.select_related("asset_job__script_job__topic__channel").get(id=thumbnail_run_id)
    except ThumbnailRun.DoesNotExist:
        logger.error(  # noqa: TRY400
            "ThumbnailRun %s not found — aborting",
            thumbnail_run_id,
            extra={"thumbnail_run_id": thumbnail_run_id},
        )
        return

    run.status = "RUNNING"
    run.celery_task_id = self.request.id
    run.started_at = timezone.now()
    run.save(update_fields=["status", "celery_task_id", "started_at"])

    try:
        from decimal import Decimal
        from pathlib import Path

        from django.conf import settings

        from ***REMOVED***.assets.models import ThumbnailOption
        from ***REMOVED***.core.storage import get_thumbnail_path
        from ***REMOVED***.services.providers.registry import get_image_provider

        media_root = Path(settings.MEDIA_ROOT)
        asset_job = run.asset_job
        script_job = asset_job.script_job
        channel = script_job.topic.channel

        title = script_job.final_title or script_job.topic.title_idea
        niche = ", ".join(channel.target_niches[:2]) if channel.target_niches else "general"
        brand_color = channel.brand_color_hex or "#FF0000"

        thumbnail_prompts = [
            (
                f"YouTube thumbnail for video titled '{title}'. Bold, eye-catching, professional. "
                f"{niche} niche. {brand_color} accent colour. No text overlay, photorealistic."
            ),
            (
                f"High-CTR YouTube thumbnail design. Topic: {title}. Dramatic lighting, emotional "
                f"impact, {niche} theme. Cinematic, 16:9, no text."
            ),
            (
                f"Minimalist YouTube thumbnail. '{title}'. Clean background, strong focal point, "
                f"{brand_color} colour scheme. Professional, {niche} niche."
            ),
        ]

        img_provider = get_image_provider(channel)
        total_cost = Decimal(0)

        for i, prompt in enumerate(thumbnail_prompts):
            responses = img_provider.generate(prompt=prompt, width=1280, height=720, num_images=1)
            if not responses:
                raise ValueError(f"Image provider returned no images for thumbnail option {i}")  # noqa: EM102, TRY003, TRY301
            img_data = responses[0]

            thumb_path = get_thumbnail_path(str(asset_job.id), i)
            thumb_path.write_bytes(img_data.image_bytes)

            ThumbnailOption.objects.update_or_create(
                asset_job=asset_job,
                option_number=i,
                defaults={
                    "thumbnail_run": run,
                    "image_file": str(thumb_path.relative_to(media_root)),
                    "prompt_used": prompt,
                    "provider": img_provider.name,
                    "is_selected": i == 0,  # first option is default-selected
                    "generation_cost_usd": Decimal(str(img_data.cost_usd)),
                },
            )
            total_cost += Decimal(str(img_data.cost_usd))

        run.options_count = len(thumbnail_prompts)
        run.total_cost_usd = total_cost
        run.provider = img_provider.name
        run.status = "COMPLETED"
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "options_count",
                "total_cost_usd",
                "provider",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        # Auto-select if no run is currently selected
        asset_job = run.asset_job
        if not asset_job.selected_thumbnail_run_id:
            asset_job.selected_thumbnail_run = run
            asset_job.save(update_fields=["selected_thumbnail_run", "updated_at"])

        logger.info(
            "ThumbnailRun complete",
            extra={
                "thumbnail_run_id": str(run.id),
                "options_count": len(thumbnail_prompts),
                "total_cost_usd": str(total_cost),
            },
        )

    except Exception as exc:
        run.status = "FAILED"
        run.notes = str(exc)[:2000]
        run.save(update_fields=["status", "notes", "updated_at"])
        raise


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_audio_mix_job",
    queue="default",
    soft_time_limit=480,
    time_limit=600,
)
def run_audio_mix_job(self, audio_mix_job_id: str) -> None:  # noqa: ANN001
    """Combine voiceover with background music to produce a mixed audio file."""
    from ***REMOVED***.production.models import AudioMixJob

    try:
        job = AudioMixJob.objects.select_related(
            "asset_job__script_job__topic__channel",
            "voiceover_run",
        ).get(id=audio_mix_job_id)
    except AudioMixJob.DoesNotExist:
        logger.error(  # noqa: TRY400
            "AudioMixJob %s not found — aborting",
            audio_mix_job_id,
            extra={"audio_mix_job_id": audio_mix_job_id},
        )
        return

    job.mark_running(task_id=self.request.id)

    try:
        from pathlib import Path

        from django.conf import settings

        from ***REMOVED***.core.storage import get_mixed_audio_path
        from ***REMOVED***.services.media.audio import AudioProcessor

        voiceover_run = job.voiceover_run
        if not voiceover_run or not voiceover_run.merged_audio_file:
            msg = "AudioMixJob requires a completed VoiceoverRun with merged_audio_file"
            raise ValueError(msg)  # noqa: TRY301

        media_root = Path(settings.MEDIA_ROOT)
        voiceover_path = voiceover_run.merged_audio_file.path
        output_path = get_mixed_audio_path(str(job.asset_job_id))
        music_volume = float(job.music_volume_pct or 0.08)

        processor = AudioProcessor()

        if job.music_file:
            music_path = job.music_file.path
            result = processor.mix_with_background_music(
                voiceover_path=voiceover_path,
                music_path=music_path,
                output_path=str(output_path),
                music_volume_pct=music_volume,
            )
        else:
            # No music: copy/normalize voiceover only
            import shutil

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(voiceover_path, str(output_path))
            result = {"path": str(output_path), "duration_sec": voiceover_run.total_duration_sec}

        # Deactivate any previous active mixes
        from ***REMOVED***.production.models import AudioMixJob as _AudioMixJob

        _AudioMixJob.objects.filter(asset_job=job.asset_job, is_active=True).exclude(id=job.id).update(is_active=False)

        job.mixed_audio_file = str(output_path.relative_to(media_root))
        job.mixed_duration_sec = result["duration_sec"]
        job.is_active = True
        job.save(update_fields=["mixed_audio_file", "mixed_duration_sec", "is_active", "updated_at"])
        job.mark_completed()

        logger.info(
            "AudioMixJob complete",
            extra={
                "audio_mix_job_id": str(job.id),
                "mixed_duration_sec": job.mixed_duration_sec,
                "has_music": bool(job.music_file),
            },
        )

    except Exception as exc:
        job.mark_failed(str(exc))
        raise


# ── Video Rendering ─────────────────────────────────────────────────────────


def _build_srt_from_whisper(words: list) -> str:
    """Build an SRT file from Whisper word-level timestamps.

    Groups words into 4-word blocks and formats as SRT subtitle entries.
    """
    if not words:
        return ""

    lines: list[str] = []
    block_size = 4
    block_idx = 1

    for i in range(0, len(words), block_size):
        block = words[i : i + block_size]
        start_sec = block[0].start if hasattr(block[0], "start") else block[0].get("start", 0)
        end_sec = block[-1].end if hasattr(block[-1], "end") else block[-1].get("end", start_sec + 2)
        text = " ".join((w.word if hasattr(w, "word") else w.get("word", "")).strip() for w in block).upper()

        def _fmt(secs: float) -> str:
            h = int(secs // 3600)
            m = int((secs % 3600) // 60)
            s = int(secs % 60)
            ms = int((secs % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines.append(f"{block_idx}\n{_fmt(start_sec)} --> {_fmt(end_sec)}\n{text}\n")
        block_idx += 1

    return "\n".join(lines)


_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _build_ass_from_whisper(words: list) -> str:
    """Build an ASS subtitle file from Whisper word-level timestamps.

    Groups into 4-word blocks. Uses Montserrat ExtraBold 72pt per CLAUDE.md spec.
    """
    if not words:
        return _ASS_HEADER

    def _fmt(secs: float) -> str:
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = secs % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    lines: list[str] = [_ASS_HEADER]
    block_size = 4

    for i in range(0, len(words), block_size):
        block = words[i : i + block_size]
        start_sec = block[0].start if hasattr(block[0], "start") else block[0].get("start", 0)
        end_sec = block[-1].end if hasattr(block[-1], "end") else block[-1].get("end", start_sec + 2)
        text = " ".join((w.word if hasattr(w, "word") else w.get("word", "")).strip() for w in block).upper()
        lines.append(f"Dialogue: 0,{_fmt(start_sec)},{_fmt(end_sec)},Default,,0,0,0,,{text}")

    return "\n".join(lines)


@shared_task(
    bind=True,
    name="***REMOVED***.pipeline.run_caption_generation",
    queue="default",
    time_limit=600,
    soft_time_limit=540,
)
def run_caption_generation(self, production_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Generate word-level captions from the merged voiceover using OpenAI Whisper API."""
    from ***REMOVED***.production.models import ProductionJob

    try:
        job = ProductionJob.objects.select_related("asset_job__selected_voiceover_run").get(id=production_job_id)
    except ProductionJob.DoesNotExist:
        logger.error("ProductionJob %s not found — aborting caption generation", production_job_id)  # noqa: TRY400
        return

    try:
        from pathlib import Path

        from django.conf import settings
        from openai import OpenAI

        from ***REMOVED***.core.storage import get_caption_path

        media_root = Path(settings.MEDIA_ROOT)

        # Always use clean voiceover for accurate Whisper transcription.
        # Music is added by FFmpeg during render — not needed for captions.
        vo_run = job.asset_job.selected_voiceover_run
        if not vo_run or not vo_run.merged_audio_file:
            logger.warning(
                "run_caption_generation: no clean voiceover — skipping",
                extra={"production_job_id": production_job_id},
            )
            return
        audio_path_str = vo_run.merged_audio_file.path

        client = OpenAI()
        with open(audio_path_str, "rb") as f:  # noqa: PTH123
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )

        words = getattr(transcript, "words", []) or []
        srt_content = _build_srt_from_whisper(words)
        ass_content = _build_ass_from_whisper(words)

        srt_path = get_caption_path(str(job.id), "srt")
        ass_path = get_caption_path(str(job.id), "ass")
        srt_path.write_text(srt_content, encoding="utf-8")
        ass_path.write_text(ass_content, encoding="utf-8")

        job.caption_srt_file = str(srt_path.relative_to(media_root))
        job.caption_ass_file = str(ass_path.relative_to(media_root))
        job.save(update_fields=["caption_srt_file", "caption_ass_file", "updated_at"])

        logger.info(
            "Caption generation complete",
            extra={
                "production_job_id": production_job_id,
                "words": len(words),
                "srt_path": str(srt_path),
            },
        )

    except Exception as exc:
        logger.error(  # noqa: G201
            "Caption generation failed: %s",
            exc,
            extra={"production_job_id": production_job_id},
            exc_info=True,
        )
        raise


@shared_task(
    bind=True,
    queue="rendering",
    time_limit=7200,  # 2 hour hard limit
    soft_time_limit=6600,
)
def render_video(self, production_job_id: str) -> None:  # noqa: ANN001
    """CPU-intensive video render task — runs on dedicated rendering queue."""
    from ***REMOVED***.production.models import ProductionJob
    from ***REMOVED***.services.media.video import VideoRenderer

    job = ProductionJob.objects.select_related(
        "asset_job__script_job__topic__channel",
        "asset_job__selected_voiceover_run",
        "asset_job__selected_image_run",
        "asset_job__selected_video_clip_run",
        "audio_mix_job",
        "scene_breakdown_job",
    ).get(id=production_job_id)
    job.mark_running(task_id=self.request.id)

    # Populate sub-job FKs from the asset chain if not already set
    _sub_job_fields: list[str] = []
    if not job.scene_breakdown_job_id:
        try:
            job.scene_breakdown_job = job.asset_job.script_job.scene_breakdown
            _sub_job_fields.append("scene_breakdown_job")
        except Exception as _exc:  # noqa: BLE001
            logger.warning(
                "render_video: could not resolve scene_breakdown_job — %s",
                _exc,
                extra={"production_job_id": production_job_id},
            )
    if not job.audio_mix_job_id:
        active_mix = job.asset_job.audio_mix_jobs.filter(is_active=True).first()
        if active_mix:
            job.audio_mix_job = active_mix
            _sub_job_fields.append("audio_mix_job")
    if _sub_job_fields:
        job.save(update_fields=(*_sub_job_fields, "updated_at"))

    try:
        # Generate captions synchronously before rendering (single task, saves overhead)
        try:
            run_caption_generation.apply(args=[production_job_id])
        except Exception as caption_err:  # noqa: BLE001
            logger.warning(
                "Caption generation failed — rendering without captions: %s",
                caption_err,
                extra={"production_job_id": production_job_id},
            )

        renderer = VideoRenderer(job)
        renderer.render()
        job.mark_completed()

        # Advance PipelineRun: RENDERING → QA, then dispatch QA task
        from django_fsm import can_proceed

        from ***REMOVED***.pipeline.models import PipelineRun

        pipeline_run = PipelineRun.objects.get(production_job=job)
        if can_proceed(pipeline_run.begin_qa):
            pipeline_run.advance_to("QA")
        run_video_qa.delay(production_job_id)

    except Exception as exc:
        job.mark_failed(str(exc))
        raise


@shared_task(bind=True, queue="rendering")
def run_video_qa(self, production_job_id: str) -> None:  # noqa: ANN001, ARG001
    from ***REMOVED***.production.models import ProductionJob
    from ***REMOVED***.services.media.video import VideoQA

    job = ProductionJob.objects.get(id=production_job_id)
    qa = VideoQA(job)
    results = qa.run_all_checks()
    job.qa_results = results
    job.qa_passed = all(results.values())
    job.save(update_fields=["qa_results", "qa_passed", "updated_at"])

    from ***REMOVED***.pipeline.models import PipelineRun

    run = PipelineRun.objects.get(production_job=job)

    if job.qa_passed:
        run.advance_to("UPLOADING")
        if run.distribution_job_id:
            upload_video.delay(str(run.distribution_job_id))
        else:
            logger.error(
                "run_video_qa: QA passed but PipelineRun has no distribution_job — upload not dispatched",
                extra={"production_job_id": production_job_id, "pipeline_run_id": str(run.id)},
            )
    else:
        job.mark_paused(f"QA failed: {results}")
        run.mark_failed(reason=f"QA failed: {list(results.keys())}")
        run.save(update_fields=["overall_status", "current_stage", "failed_at", "last_agent_decision", "updated_at"])


# ── Upload ───────────────────────────────────────────────────────────────────


@shared_task(bind=True, queue="uploads")
def upload_video(self, distribution_job_id: str) -> None:  # noqa: ANN001
    from ***REMOVED***.distribution.models import DistributionJob
    from ***REMOVED***.services.youtube.client import YouTubeClient
    from ***REMOVED***.services.youtube.exceptions import YouTubeAuthError

    job = DistributionJob.objects.select_related("channel", "production_job").get(id=distribution_job_id)
    job.mark_running(task_id=self.request.id)

    youtube_account = job.channel.get_youtube_account()
    if youtube_account is None:
        msg = f"Channel {job.channel.slug} has no active YouTube SocialAccount"
        raise YouTubeAuthError(msg)

    try:
        client = YouTubeClient.from_social_account(youtube_account)
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
        raise


# ── Post-Upload Stubs ────────────────────────────────────────────────────────


@shared_task(bind=True, queue="uploads")
def set_video_thumbnail(self, distribution_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Upload selected thumbnail to YouTube. Stub — real implementation in Phase 8."""
    logger.info("set_video_thumbnail called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube thumbnail upload via YouTube Data API  # noqa: FIX002


@shared_task(bind=True, queue="uploads")
def post_pinned_comment(self, distribution_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Post pinned comment on the uploaded video. Stub — real implementation in Phase 8."""
    logger.info("post_pinned_comment called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube comment posting and pinning via YouTube Data API  # noqa: FIX002


@shared_task(bind=True, queue="uploads")
def add_to_playlist(self, distribution_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Add video to configured playlists. Stub — real implementation in Phase 8."""
    logger.info("add_to_playlist called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement YouTube playlist assignment via YouTube Data API  # noqa: FIX002


@shared_task(bind=True, queue="uploads")
def upload_youtube_short(self, distribution_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Upload the Shorts variant of the video. Stub — real implementation in Phase 8."""
    logger.info("upload_youtube_short called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Upload 9:16 cropped Shorts variant via YouTube Data API  # noqa: FIX002


@shared_task(bind=True, queue="uploads")
def cross_post_social(self, distribution_job_id: str) -> None:  # noqa: ANN001, ARG001
    """Cross-post video clip to TikTok/Instagram/Twitter. Stub — real implementation in Phase 8."""
    logger.info("cross_post_social called for distribution_job_id=%s (stub)", distribution_job_id)
    # TODO: Implement cross-platform posting (TikTok, Instagram Reels, Twitter/X)  # noqa: FIX002


# ── Analytics ────────────────────────────────────────────────────────────────


@shared_task(queue="analytics")
def sync_channel_analytics(channel_id: str) -> None:
    """Pull analytics for all published videos on a channel."""
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.distribution.models import DistributionJob
    from ***REMOVED***.services.youtube.client import YouTubeClient
    from ***REMOVED***.services.youtube.exceptions import YouTubeAuthError

    channel = Channel.objects.get(id=channel_id)
    youtube_account = channel.get_youtube_account()
    if youtube_account is None:
        msg = f"Channel {channel.slug} has no active YouTube SocialAccount"
        raise YouTubeAuthError(msg)
    client = YouTubeClient.from_social_account(youtube_account)

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
    """Parse agent output and bulk-create TopicIdea records, then write back
    token usage, cost, and raw data snapshots to the ResearchJob.

    Args:
        job: ResearchJob instance
        result: RunResult from Runner.run()
        channel: Channel instance
    """
    from ***REMOVED***.research.choices import CompetitionLevel
    from ***REMOVED***.research.choices import TrendDirection
    from ***REMOVED***.research.models import TopicIdea

    output: ResearchAgentOutput = result.output

    # ── Token usage and cost ─────────────────────────────────────────────────
    usage = result.usage()
    total_input = usage.request_tokens or 0
    total_output = usage.response_tokens or 0
    total_tokens = usage.total_tokens or (total_input + total_output)

    cost_usd = (
        Decimal(str(total_input)) * _GPT4O_INPUT_COST_PER_M / Decimal(1000000)
        + Decimal(str(total_output)) * _GPT4O_OUTPUT_COST_PER_M / Decimal(1000000)
    ).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)

    agent_run_id = ""

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
    from ***REMOVED***.channels.models import ChannelCompetitor

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


def _save_script_results(  # noqa: PLR0915
    job: Any,
    result: Any,
    version_number: int = 1,
    change_summary: str = "Agent v1 — auto-saved from pipeline",
) -> None:
    """Parse the ScriptAgent RunResult and persist all output fields to ScriptJob.

    Args:
        job: ScriptJob instance
        result: RunResult from Runner.run()
        version_number: ScriptRevision version number to create
        change_summary: Human-readable description of what changed in this revision
    """
    from ***REMOVED***.agents.schemas import ScriptAgentOutput

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
            "subject": b.subject,
            "setting": b.setting,
            "lighting": b.lighting,
            "camera_angle": b.camera_angle,
            "colour_palette": list(b.colour_palette),
            "style_preset": b.style_preset,
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
    # Normalize LLM-returned hook type to the Literal values expected by Hook schema.
    _HOOK_TYPE_ALIASES: dict[str, str] = {  # noqa: N806
        "question": "question",
        "statement": "statement",
        "bold claim": "statement",
        "story": "story",
        "story teaser": "story",
        "stat": "stat",
        "shocking stat": "stat",
        "contrarian": "contrarian",
        "contrarian take": "contrarian",
    }
    generated_hooks: list[dict[str, Any]] = []
    if output.hook_used:
        hook_type_raw = (output.quality_flags.hook_type or "statement").lower().strip()
        hook_type = _HOOK_TYPE_ALIASES.get(hook_type_raw, "statement")
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

    # Auto-generate TTS segments from script sections (1 segment per section)
    cursor_sec = 0.0
    segments: list[dict[str, Any]] = []
    for i, section in enumerate(output.sections):
        text = section.content.strip()
        if not text:
            continue
        approx_duration = len(text.split()) / 130.0 * 60.0  # 130 WPM average
        segments.append(
            {
                "segment_id": i + 1,
                "text": text,
                "section": section.tag,
                "approx_start_sec": round(cursor_sec, 2),
                "approx_end_sec": round(cursor_sec + approx_duration, 2),
            }
        )
        cursor_sec += approx_duration + 0.2  # 200ms inter-segment pause

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
    job.narrative_mode = output.narrative_mode or ""
    job.final_title = seo.final_title
    job.final_description = seo.description
    job.seo_tags = seo.tags
    job.chapters = chapters
    job.pinned_comment = seo.pinned_comment
    job.thumbnail_text = seo.thumbnail_text
    job.thumbnail_emotion = seo.thumbnail_emotion
    job.search_hashtags = list(seo.search_hashtags)
    job.segments = segments

    job.save(
        update_fields=[
            "script_text",
            "sections",
            "segments",
            "word_count",
            "estimated_duration_mins",
            "broll_suggestions",
            "research_sources",
            "hook_score",
            "generated_hooks",
            "quality_flags",
            "ready_for_production",
            "revision_notes",
            "narrative_mode",
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

    # Auto-create revision — replaces save_script_draft tool call
    from ***REMOVED***.scripts.models import ScriptRevision

    ScriptRevision.objects.create(
        script_job=job,
        version_number=version_number,
        script_text=output.script_text,
        word_count=output.word_count,
        change_summary=change_summary,
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


def _create_or_update_snapshot(client: YouTubeClient, job: Any, snapshot_day: int) -> None:  # noqa: ARG001
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
