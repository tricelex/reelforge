from __future__ import annotations

import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django_fsm import can_proceed

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.core.storage import get_clip_downloaded_path
from ***REMOVED***.core.storage import get_clip_render_path

logger = logging.getLogger("***REMOVED***.clipping")


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.download_source_video",
    max_retries=3,
    default_retry_delay=60,
    queue="clipping",
)
def download_source_video(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.error("ClippingJob not found", extra={"id": clipping_job_id})
        return

    job.celery_task_id = self.request.id
    job.save(update_fields=["celery_task_id", "updated_at"])

    try:
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
            transcribe_video.delay(clipping_job_id)

    except Exception as exc:
        logger.error(
            "Download failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            exc_info=True,
        )
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.transcribe_video",
    max_retries=3,
    default_retry_delay=120,
    queue="clipping",
)
def transcribe_video(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.select_related("channel").get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.error("ClippingJob not found for transcription", extra={"id": clipping_job_id})
        return

    try:
        from ***REMOVED***.services.transcription.whisper import WhisperTranscriptionService

        video_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
        service = WhisperTranscriptionService(api_key=settings.OPENAI_API_KEY)
        result = service.transcribe(video_path)

        job.transcript_text = result.transcript_text
        job.transcript_json = result.transcript_json
        job.transcription_cost_usd = result.cost_usd
        job.transcription_provider = result.provider
        job.save(update_fields=[
            "transcript_text", "transcript_json",
            "transcription_cost_usd", "transcription_provider", "updated_at",
        ])

        if can_proceed(job.begin_analysis):
            job.begin_analysis()
            job.save(update_fields=["status", "updated_at"])
            analyze_clips.delay(clipping_job_id)

    except Exception as exc:
        logger.error(
            "Transcription failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 120)


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.analyze_clips",
    max_retries=2,
    default_retry_delay=60,
    queue="clipping",
)
def analyze_clips(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.select_related("channel").get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.error("ClippingJob not found for analysis", extra={"id": clipping_job_id})
        return

    try:
        from ***REMOVED***.clipping.services import ClipAnalysisService

        service = ClipAnalysisService(job)
        candidates = service.analyze()

        # Check if auto-approve applies for all target accounts
        target_accounts = job.target_accounts.all()
        all_auto_approve = all(a.auto_approve_clips for a in target_accounts) and target_accounts.exists()

        if all_auto_approve:
            for candidate in candidates:
                candidate.approved = True
                candidate.status = ClipCandidate.CandidateStatus.APPROVED
                candidate.save(update_fields=["approved", "status", "updated_at"])

            if can_proceed(job.begin_rendering):
                job.begin_rendering()
                job.save(update_fields=["status", "updated_at"])
                for candidate in candidates:
                    render_clip.delay(str(candidate.id))
        else:
            if can_proceed(job.await_clip_approval):
                job.await_clip_approval()
                job.save(update_fields=["status", "updated_at"])

    except Exception as exc:
        logger.error(
            "Clip analysis failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.render_clip",
    max_retries=2,
    default_retry_delay=300,
    queue="rendering",
    time_limit=1800,
    soft_time_limit=1700,
)
def render_clip(self, clip_candidate_id: str) -> None:
    try:
        candidate = ClipCandidate.objects.select_related(
            "clipping_job__channel"
        ).get(id=clip_candidate_id)
    except ClipCandidate.DoesNotExist:
        logger.error("ClipCandidate not found", extra={"id": clip_candidate_id})
        return

    render = ClipRender.objects.create(
        candidate=candidate,
        format=ClipRender.Format.VERTICAL_9_16,
        celery_task_id=self.request.id,
        status=ClipRender.RenderStatus.RUNNING,
    )

    try:
        from ***REMOVED***.services.media.clip_renderer import ClipRenderConfig
        from ***REMOVED***.services.media.clip_renderer import ClipRenderer

        job = candidate.clipping_job
        channel = job.channel

        source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
        output_path = get_clip_render_path(str(candidate.id), render.format)

        config = ClipRenderConfig(
            source_path=source_path,
            output_path=output_path,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
            hook_text=candidate.hook_text if render.include_title_card else "",
            transcript_json=job.transcript_json if render.include_captions else {},
            intro_path=Path(channel.channel_intro_file.path) if channel.channel_intro_file else None,
            outro_path=Path(channel.channel_outro_file.path) if channel.channel_outro_file else None,
        )

        renderer = ClipRenderer(config)
        renderer.render()

        render.video_file = str(output_path.relative_to(settings.MEDIA_ROOT))
        render.file_size_bytes = output_path.stat().st_size
        render.status = ClipRender.RenderStatus.COMPLETED
        render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])

        candidate.status = ClipCandidate.CandidateStatus.RENDERED
        candidate.save(update_fields=["status", "updated_at"])

        for account in job.target_accounts.filter(is_active=True):
            post = ClipPost.objects.create(render=render, social_account=account)
            post_clip.delay(str(post.id))

    except Exception as exc:
        render.status = ClipRender.RenderStatus.FAILED
        render.last_error = str(exc)
        render.save(update_fields=["status", "last_error", "updated_at"])
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 300)


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.post_clip",
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
        logger.error("ClipPost not found", extra={"id": clip_post_id})
        return

    clip_post.status = ClipPost.PostStatus.POSTING
    clip_post.celery_task_id = self.request.id
    clip_post.save(update_fields=["status", "celery_task_id", "updated_at"])

    try:
        from django.utils import timezone

        from ***REMOVED***.services.providers.registry import get_distribution_provider

        provider = get_distribution_provider(clip_post.social_account)
        result = provider.post_clip(clip_post)

        if result.success:
            clip_post.platform_post_id = result.platform_post_id
            clip_post.platform_url = result.platform_url
            clip_post.status = ClipPost.PostStatus.POSTED
            clip_post.posted_at = timezone.now()
            clip_post.save(update_fields=[
                "platform_post_id", "platform_url", "status", "posted_at", "updated_at",
            ])
        else:
            clip_post.status = ClipPost.PostStatus.FAILED
            clip_post.last_error = result.error_message
            clip_post.save(update_fields=["status", "last_error", "updated_at"])

    except Exception as exc:
        clip_post.last_error = str(exc)
        clip_post.save(update_fields=["last_error", "updated_at"])
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 120)


@shared_task(
    bind=True,
    name="***REMOVED***.clipping.sync_clip_analytics",
    max_retries=2,
    queue="analytics",
)
def sync_clip_analytics(self, clip_post_id: str) -> None:
    try:
        clip_post = ClipPost.objects.select_related("social_account").get(id=clip_post_id)
    except ClipPost.DoesNotExist:
        logger.error("ClipPost not found for analytics sync", extra={"id": clip_post_id})
        return

    try:
        from django.utils import timezone

        from ***REMOVED***.services.providers.registry import get_distribution_provider

        provider = get_distribution_provider(clip_post.social_account)
        result = provider.get_analytics(clip_post)

        clip_post.views = result.views
        clip_post.likes = result.likes
        clip_post.comments = result.comments
        clip_post.shares = result.shares
        clip_post.revenue_est_usd = result.revenue_est_usd
        clip_post.last_analytics_sync = timezone.now()
        clip_post.save(update_fields=[
            "views", "likes", "comments", "shares",
            "revenue_est_usd", "last_analytics_sync", "updated_at",
        ])

    except Exception as exc:
        logger.warning(
            "Analytics sync failed",
            extra={"clip_post_id": clip_post_id, "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=300)
