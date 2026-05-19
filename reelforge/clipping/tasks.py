from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import ffmpeg
from celery import shared_task
from django.conf import settings
from django_fsm import can_proceed

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRender
from reelforge.clipping.models import ClipStyleConfig
from reelforge.clipping.models import ClipTimedOverlay
from reelforge.core.storage import get_clip_downloaded_path
from reelforge.core.storage import get_clip_render_path
from reelforge.services.media.clip_render_pipeline import ClipRenderPipeline
from reelforge.services.media.clip_render_pipeline import GatePausedException
from reelforge.services.media.clip_render_pipeline import PipelineRenderConfig

logger = logging.getLogger("reelforge.clipping")


@shared_task(
    bind=True,
    max_retries=3,
    queue="clipping",
)
def download_source_video(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.exception("ClippingJob not found", extra={"id": clipping_job_id})
        return

    job.celery_task_id = self.request.id
    job.save(update_fields=["celery_task_id", "updated_at"])

    if job.source_type == ClippingJob.SourceType.UPLOAD and not job.source_video_file:
        msg = "UPLOAD job has no source_video_file set"
        job.mark_failed(error=msg)
        job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
        logger.error(msg, extra={"clipping_job_id": clipping_job_id})
        return

    try:
        if job.source_type == ClippingJob.SourceType.UPLOAD:
            # File already uploaded — just point downloaded_file at it.
            job.downloaded_file = job.source_video_file
            job.save(update_fields=["downloaded_file", "updated_at"])

        else:
            # YOUTUBE_URL and DIRECT_URL both go through yt_dlp.
            import yt_dlp

            output_path = get_clip_downloaded_path(str(job.id))
            output_path.parent.mkdir(parents=True, exist_ok=True)

            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": str(output_path),
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(job.source_url, download=True)
                job.source_title = info.get("title", "")
                job.source_duration_sec = int(info.get("duration", 0))

            job.downloaded_file = str(output_path.relative_to(settings.MEDIA_ROOT))
            job.save(update_fields=["downloaded_file", "source_title", "source_duration_sec", "updated_at"])

        if can_proceed(job.begin_transcription):
            job.begin_transcription()
            job.save(update_fields=["status", "updated_at"])
            from reelforge.clipping.sse import emit_job_event
            emit_job_event(str(job.id), "status_changed", {"status": job.status})
            transcribe_video.delay(clipping_job_id)

    except Exception as exc:
        logger.error(
            "Download failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            exc_info=True,
        )
        raise self.retry(exc=exc, countdown=2**self.request.retries * 60)


@shared_task(
    bind=True,
    name="reelforge.clipping.transcribe_video",
    max_retries=3,
    default_retry_delay=120,
    queue="clipping",
)
def transcribe_video(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.select_related("social_account").get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.exception("ClippingJob not found for transcription", extra={"id": clipping_job_id})
        return

    audio_path: Path | None = None
    try:
        from reelforge.services.transcription.whisper import WhisperTranscriptionService

        video_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name

        # Extract audio-only at 16kHz mono to stay under the Whisper 25MB file limit.
        # A full MP4 download can be 100s of MB; 16kHz mono MP3 is typically <5MB per hour.
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            audio_path = Path(tmp.name)
        (
            ffmpeg.input(str(video_path))
            .output(str(audio_path), ac=1, ar=16000, audio_bitrate="32k", format="mp3")
            .overwrite_output()
            .run(quiet=True)
        )

        service = WhisperTranscriptionService(api_key=settings.OPENAI_API_KEY)
        result = service.transcribe(audio_path)

        job.transcript_text = result.transcript_text
        job.transcript_json = result.transcript_json
        job.transcription_cost_usd = result.cost_usd
        job.transcription_provider = result.provider
        job.save(
            update_fields=[
                "transcript_text",
                "transcript_json",
                "transcription_cost_usd",
                "transcription_provider",
                "updated_at",
            ]
        )

        if can_proceed(job.begin_analysis):
            job.begin_analysis()
            job.save(update_fields=["status", "updated_at"])
            from reelforge.clipping.sse import emit_job_event
            emit_job_event(str(job.id), "status_changed", {"status": job.status})
            analyze_clips.delay(clipping_job_id)

    except Exception as exc:
        logger.error(
            "Transcription failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            exc_info=True,
        )
        if self.request.retries >= self.max_retries:
            if can_proceed(job.mark_failed):
                job.mark_failed(error=str(exc))
                job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
            return
        raise self.retry(exc=exc, countdown=2**self.request.retries * 120)
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)


@shared_task(
    bind=True,
    name="reelforge.clipping.analyze_clips",
    max_retries=2,
    default_retry_delay=60,
    queue="clipping",
)
def analyze_clips(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.select_related("social_account").get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.exception("ClippingJob not found for analysis", extra={"id": clipping_job_id})
        return

    try:
        from reelforge.clipping.analysis_helpers import build_analysis_manifest
        from reelforge.clipping.analysis_helpers import merge_transcript_with_diarization
        from reelforge.clipping.analysis_helpers import run_face_detection_for_speakers
        from reelforge.clipping.analysis_helpers import run_scene_detection
        from reelforge.clipping.analysis_helpers import run_speaker_diarization
        from reelforge.clipping.services import ClipAnalysisService
        from reelforge.clipping.sse import emit_job_event

        video_path = str(job.downloaded_file.path) if job.downloaded_file else None
        if not video_path:
            msg = "No downloaded file on job"
            raise ValueError(msg)

        # 1. Speaker diarization (may fail gracefully)
        try:
            diarization_result = run_speaker_diarization(video_path)
        except Exception as exc:
            logger.warning(
                "Diarization failed — continuing without speaker data",
                extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            )
            diarization_result = {"segments": []}

        # 2. Scene detection (always graceful)
        scene_cuts = run_scene_detection(video_path)

        # 3. Face detection per speaker segment
        try:
            face_mappings = run_face_detection_for_speakers(video_path, diarization_result)
        except Exception as exc:
            logger.warning(
                "Face detection failed — continuing without face data",
                extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
                exc_info=True,
            )
            face_mappings = {}

        # 4. Merge transcript + diarization
        enriched_transcript = merge_transcript_with_diarization(
            job.transcript_json or {}, diarization_result
        )

        # 5. Extract video duration from transcript metadata
        video_duration: float | None = None
        raw_duration = (job.transcript_json or {}).get("duration")
        if raw_duration is not None:
            try:
                video_duration = float(raw_duration)
            except (TypeError, ValueError):
                logger.warning(
                    "Could not parse video duration from transcript_json",
                    extra={"clipping_job_id": clipping_job_id, "raw_duration": raw_duration},
                )

        # 6. LLM analysis with full timing context
        service = ClipAnalysisService(job)
        candidates = service.analyze(
            enriched_transcript=enriched_transcript,
            diarization=diarization_result,
            scene_cuts=scene_cuts,
            video_duration=video_duration,
        )

        # 7. Build and save analysis manifest
        manifest = build_analysis_manifest(
            transcript=enriched_transcript,
            diarization=diarization_result,
            face_mappings=face_mappings,
            scene_cuts=scene_cuts,
            candidates=candidates,
        )
        job.analysis_manifest = manifest

        # 8. Transition — always await approval, no auto-approve
        if can_proceed(job.await_clip_approval):
            job.await_clip_approval()
        job.save(
            update_fields=[
                "status",
                "analysis_manifest",
                "analysis_cost_usd",
                "analysis_provider",
                "updated_at",
            ]
        )

        emit_job_event(
            str(job.id),
            "analysis_complete",
            {"status": job.status, "candidate_count": len(candidates)},
        )

    except Exception as exc:
        logger.error(
            "Clip analysis failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            exc_info=True,
        )
        if self.request.retries >= self.max_retries:
            if can_proceed(job.mark_failed):
                job.mark_failed(error=str(exc))
                job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                from reelforge.clipping.sse import emit_job_event
                emit_job_event(str(job.id), "job_failed", {"error": str(exc), "stage": "analysis"})
            return
        raise self.retry(exc=exc, countdown=2**self.request.retries * 60)


@shared_task(
    bind=True,
    name="reelforge.clipping.render_clip",
    max_retries=2,
    default_retry_delay=300,
    queue="rendering",
    time_limit=3600,
    soft_time_limit=3500,
)
def render_clip(
    self,
    clip_candidate_id: str,
    start_from_stage: int = 1,
    clip_render_id: str | None = None,
) -> None:
    """Render a ClipCandidate through the multi-stage pipeline.

    When clip_render_id is provided, resumes an existing render from
    start_from_stage. Otherwise creates a new ClipRender record.
    """
    try:
        candidate = ClipCandidate.objects.select_related(
            "clipping_job__social_account"
        ).get(id=clip_candidate_id)
    except ClipCandidate.DoesNotExist:
        logger.exception("ClipCandidate not found", extra={"id": clip_candidate_id})
        return

    layout_config = ClipLayoutConfig.objects.filter(candidate=candidate).first()
    style_config = ClipStyleConfig.objects.filter(candidate=candidate).first()
    timed_overlays = list(
        ClipTimedOverlay.objects.filter(candidate=candidate).order_by("start_sec")
    )

    render_format = (
        layout_config.render_format if layout_config is not None else ClipRender.Format.VERTICAL_9_16
    )

    if clip_render_id is not None:
        try:
            render = ClipRender.objects.get(id=clip_render_id, candidate=candidate)
        except ClipRender.DoesNotExist:
            logger.exception(
                "ClipRender not found for retry",
                extra={"clip_render_id": clip_render_id, "candidate_id": clip_candidate_id},
            )
            return
        render.celery_task_id = self.request.id
        render.status = ClipRender.RenderStatus.RUNNING
        render.save(update_fields=["celery_task_id", "status", "updated_at"])
    else:
        render = ClipRender.objects.create(
            candidate=candidate,
            format=render_format,
            celery_task_id=self.request.id,
            status=ClipRender.RenderStatus.RUNNING,
        )

    try:
        job = candidate.clipping_job
        source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
        output_path = get_clip_render_path(str(candidate.id), render.format)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        pipeline_config = PipelineRenderConfig(
            source_path=source_path,
            output_path=output_path,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
            hook_text=candidate.hook_text,
            transcript_json=job.transcript_json,
            layout_config=layout_config,
            style_config=style_config,
            timed_overlays=timed_overlays,
            render_id=str(render.id),
        )

        gate_stages = set(candidate.render_gates or [])

        try:
            pipeline = ClipRenderPipeline(pipeline_config)
            pipeline.run(
                start_from_stage=start_from_stage,
                pause_after_stages=gate_stages,
            )
        except GatePausedException as exc:
            render.status = ClipRender.RenderStatus.PAUSED_AT_GATE
            render.paused_at_stage = exc.stage_order
            render.save(update_fields=["status", "paused_at_stage", "updated_at"])
            logger.info(
                "Render paused at gate",
                extra={
                    "render_id": str(render.id),
                    "candidate_id": str(candidate.id),
                    "paused_at_stage": exc.stage_order,
                },
            )
            from reelforge.clipping.sse import emit_job_event
            emit_job_event(
                str(candidate.clipping_job_id),
                "render_paused",
                {
                    "render_id": str(render.id),
                    "candidate_id": str(candidate.id),
                    "paused_at_stage": exc.stage_order,
                },
            )
            return  # Do not retry — this is an intentional pause

        # Write back speaker detection results from TrimAndCropStage if available
        trim_stage = next((s for s in pipeline._stages if s.name == "trim_and_crop"), None)
        if (
            layout_config is not None
            and trim_stage is not None
            and hasattr(trim_stage, "last_speaker_crop_result")
            and trim_stage.last_speaker_crop_result is not None
        ):
            layout_config.face_detected = trim_stage.last_speaker_crop_result.face_detected
            layout_config.detection_confidence = trim_stage.last_speaker_crop_result.confidence
            layout_config.save(update_fields=["face_detected", "detection_confidence", "updated_at"])

        render.video_file = str(output_path.relative_to(settings.MEDIA_ROOT))
        render.file_size_bytes = output_path.stat().st_size
        render.status = ClipRender.RenderStatus.COMPLETED
        render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])
        from reelforge.clipping.sse import emit_job_event
        emit_job_event(
            str(candidate.clipping_job_id),
            "render_complete",
            {
                "render_id": str(render.id),
                "candidate_id": str(candidate.id),
                "video_url": render.video_file.url if render.video_file else None,
            },
        )

        candidate.status = ClipCandidate.CandidateStatus.RENDERED
        candidate.save(update_fields=["status", "updated_at"])

        post = ClipPost.objects.create(render=render, social_account=job.social_account)
        post_clip.delay(str(post.id))

    except Exception as exc:
        render.status = ClipRender.RenderStatus.FAILED
        render.last_error = str(exc)
        render.save(update_fields=["status", "last_error", "updated_at"])
        from reelforge.clipping.sse import emit_job_event
        emit_job_event(
            str(candidate.clipping_job_id),
            "render_failed",
            {"render_id": str(render.id), "candidate_id": str(candidate.id), "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=2**self.request.retries * 300)


def _get_preview_font(size: int) -> object:
    """Return the best available PIL font for style previews."""
    from PIL import ImageFont

    static_root = getattr(settings, "STATIC_ROOT", None)
    if static_root:
        fonts_dir = Path(static_root) / "fonts"
    else:
        fonts_dir = Path(settings.BASE_DIR) / "reelforge" / "static" / "fonts"

    candidates = [
        fonts_dir / "Montserrat-Bold.ttf",
        fonts_dir / "DejaVuSans-Bold.ttf",
    ]
    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


@shared_task(
    bind=True,
    name="reelforge.clipping.preview_clip_style",
    max_retries=1,
    queue="clipping",
    time_limit=60,
    soft_time_limit=55,
)
def preview_clip_style(self, style_config_id: str) -> None:
    """Generate a static frame preview of the style config (PIL-based, no ffmpeg).

    Extracts mid-clip frame, overlays watermark text + sample caption, saves
    to ClipStyleConfig.preview_image.
    """
    import io

    import cv2
    from django.core.files.base import ContentFile
    from PIL import Image
    from PIL import ImageDraw

    try:
        style_config = ClipStyleConfig.objects.select_related(
            "candidate__clipping_job"
        ).get(id=style_config_id)
    except ClipStyleConfig.DoesNotExist:
        logger.exception("ClipStyleConfig not found", extra={"id": style_config_id})
        return

    candidate = style_config.candidate
    job = candidate.clipping_job

    if not job.downloaded_file:
        logger.warning(
            "Cannot generate style preview — source video not downloaded",
            extra={"style_config_id": style_config_id},
        )
        return

    source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
    mid_sec = (candidate.start_sec + candidate.end_sec) / 2

    cap = cv2.VideoCapture(str(source_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid_sec * fps))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        logger.warning(
            "Could not extract frame for style preview",
            extra={"style_config_id": style_config_id},
        )
        return

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(img)

    if (
        style_config.watermark_enabled
        and style_config.watermark_type == "TEXT"
        and style_config.watermark_text
    ):
        font = _get_preview_font(size=style_config.watermark_size)
        wm_positions = {
            "BOTTOM_RIGHT": (img.width - 150, img.height - 60),
            "TOP_LEFT": (10, 10),
            "TOP_RIGHT": (img.width - 150, 10),
            "BOTTOM_LEFT": (10, img.height - 60),
        }
        pos = wm_positions.get(style_config.watermark_position, (img.width - 150, img.height - 60))
        draw.text(
            pos,
            style_config.watermark_text,
            fill=(255, 255, 255, int(255 * style_config.watermark_opacity)),
            font=font,
        )

    if style_config.caption_enabled:
        font = _get_preview_font(size=style_config.caption_size // 2)
        draw.text(
            (img.width // 2 - 200, img.height - 200),
            "Sample caption text",
            fill=(255, 255, 255),
            font=font,
        )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    filename = f"style_preview_{style_config_id}.jpg"
    style_config.preview_image.save(filename, ContentFile(buf.getvalue()), save=True)
    logger.info(
        "Style preview generated",
        extra={"style_config_id": style_config_id, "filename": filename},
    )


@shared_task(
    bind=True,
    name="reelforge.clipping.post_clip",
    max_retries=3,
    default_retry_delay=120,
    queue="clipping",
)
def post_clip(self, clip_post_id: str) -> None:
    try:
        clip_post = ClipPost.objects.select_related(
            "render__candidate__clipping_job",
            "social_account",
        ).get(id=clip_post_id)
    except ClipPost.DoesNotExist:
        logger.exception("ClipPost not found", extra={"id": clip_post_id})
        return

    clip_post.status = ClipPost.PostStatus.POSTING
    clip_post.celery_task_id = self.request.id
    clip_post.save(update_fields=["status", "celery_task_id", "updated_at"])

    try:
        from django.utils import timezone

        from reelforge.services.providers.registry import get_distribution_provider

        provider = get_distribution_provider(clip_post.social_account)
        result = provider.post_clip(clip_post)

        if result.success:
            clip_post.platform_post_id = result.platform_post_id
            clip_post.platform_url = result.platform_url
            clip_post.status = ClipPost.PostStatus.POSTED
            clip_post.posted_at = timezone.now()
            clip_post.save(
                update_fields=[
                    "platform_post_id",
                    "platform_url",
                    "status",
                    "posted_at",
                    "updated_at",
                ]
            )
            from reelforge.clipping.sse import emit_job_event
            emit_job_event(
                str(clip_post.render.candidate.clipping_job_id),
                "post_complete",
                {"post_id": str(clip_post.id), "platform_url": clip_post.platform_url},
            )
        else:
            clip_post.status = ClipPost.PostStatus.FAILED
            clip_post.last_error = result.error_message
            clip_post.save(update_fields=["status", "last_error", "updated_at"])

    except Exception as exc:
        clip_post.last_error = str(exc)
        clip_post.save(update_fields=["last_error", "updated_at"])
        raise self.retry(exc=exc, countdown=2**self.request.retries * 120)


@shared_task(
    bind=True,
    name="reelforge.clipping.preview_clip_layout",
    max_retries=1,
    queue="clipping",
    time_limit=120,
    soft_time_limit=100,
)
def preview_clip_layout(self, layout_config_id: str) -> None:
    """Generate a JPEG preview image showing crop region(s) overlaid on a source frame.

    For SMART_CROP: draws the detected (or manual) 9:16 crop window in green.
    For SPATIAL_STACK: draws region A (green) and region B (blue).
    For CENTER_CROP: draws the center 9:16 crop window in green.
    Saves the result to ClipLayoutConfig.preview_image.
    """

    import cv2
    from django.core.files.base import ContentFile

    try:
        lc = ClipLayoutConfig.objects.select_related(
            "candidate__clipping_job"
        ).get(id=layout_config_id)
    except ClipLayoutConfig.DoesNotExist:
        logger.exception("ClipLayoutConfig not found", extra={"id": layout_config_id})
        return

    candidate = lc.candidate
    job = candidate.clipping_job

    if not job.downloaded_file:
        logger.warning(
            "Cannot generate preview — source video not downloaded",
            extra={"layout_config_id": layout_config_id},
        )
        return

    source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
    mid_sec = (candidate.start_sec + candidate.end_sec) / 2

    cap = cv2.VideoCapture(str(source_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid_sec * fps))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        logger.warning(
            "Could not extract frame for preview",
            extra={"layout_config_id": layout_config_id, "mid_sec": mid_sec},
        )
        return

    GREEN = (0, 220, 0)
    BLUE = (220, 100, 0)
    thickness = max(3, src_h // 200)

    if lc.render_mode == ClipLayoutConfig.RenderMode.SPATIAL_STACK and lc.has_spatial_regions:
        cv2.rectangle(
            frame,
            (lc.region_a_x, lc.region_a_y),
            (lc.region_a_x + lc.region_a_w, lc.region_a_y + lc.region_a_h),
            GREEN,
            thickness,
        )
        cv2.putText(
            frame, lc.region_a_label, (lc.region_a_x + 10, lc.region_a_y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, GREEN, 2,
        )
        cv2.rectangle(
            frame,
            (lc.region_b_x, lc.region_b_y),
            (lc.region_b_x + lc.region_b_w, lc.region_b_y + lc.region_b_h),
            BLUE,
            thickness,
        )
        cv2.putText(
            frame, lc.region_b_label, (lc.region_b_x + 10, lc.region_b_y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, BLUE, 2,
        )
    else:
        # SMART_CROP or CENTER_CROP — draw the 9:16 crop window
        crop_w = int(9 / 16 * src_h)
        if lc.render_mode == ClipLayoutConfig.RenderMode.SMART_CROP and lc.has_manual_smart_crop:
            crop_x = lc.manual_crop_x
            crop_w = lc.manual_crop_w
            crop_h = lc.manual_crop_h
        else:
            crop_x = max(0, (src_w - crop_w) // 2)
            crop_h = src_h
        cv2.rectangle(
            frame,
            (crop_x, 0),
            (crop_x + crop_w, crop_h),
            GREEN,
            thickness,
        )

    # Scale preview to a reasonable width for fast loading
    preview_w = min(src_w, 960)
    scale = preview_w / src_w
    preview_h = int(src_h * scale)
    preview_frame = cv2.resize(frame, (preview_w, preview_h))

    ok, buf = cv2.imencode(".jpg", preview_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        logger.error("Failed to encode preview JPEG", extra={"layout_config_id": layout_config_id})
        return

    filename = f"preview_{layout_config_id}.jpg"
    lc.preview_image.save(filename, ContentFile(buf.tobytes()), save=True)
    from reelforge.clipping.sse import emit_job_event
    emit_job_event(
        str(lc.candidate.clipping_job_id),
        "preview_ready",
        {
            "layout_config_id": str(lc.id),
            "preview_url": lc.preview_image.url if lc.preview_image else None,
        },
    )
    logger.info(
        "Preview image generated",
        extra={"layout_config_id": layout_config_id, "filename": filename},
    )


@shared_task(
    bind=True,
    name="reelforge.clipping.sync_clip_analytics",
    max_retries=2,
    queue="analytics",
)
def sync_clip_analytics(self, clip_post_id: str) -> None:
    try:
        clip_post = ClipPost.objects.select_related("social_account").get(id=clip_post_id)
    except ClipPost.DoesNotExist:
        logger.exception("ClipPost not found for analytics sync", extra={"id": clip_post_id})
        return

    try:
        from django.utils import timezone

        from reelforge.services.providers.registry import get_distribution_provider

        provider = get_distribution_provider(clip_post.social_account)
        result = provider.get_analytics(clip_post)

        clip_post.views = result.views
        clip_post.likes = result.likes
        clip_post.comments = result.comments
        clip_post.shares = result.shares
        clip_post.revenue_est_usd = result.revenue_est_usd
        clip_post.last_analytics_sync = timezone.now()
        clip_post.save(
            update_fields=[
                "views",
                "likes",
                "comments",
                "shares",
                "revenue_est_usd",
                "last_analytics_sync",
                "updated_at",
            ]
        )

    except Exception as exc:
        logger.warning(
            "Analytics sync failed",
            extra={"clip_post_id": clip_post_id, "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=300)
