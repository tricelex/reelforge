from __future__ import annotations

import logging

from django.contrib import admin
from django.contrib import messages
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.html import format_html_join
from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRender

logger = logging.getLogger("reelforge.clipping")


class ClipRenderInline(TabularInline):
    model = ClipRender
    extra = 0
    can_delete = False
    readonly_fields = (
        "format",
        "status",
        "video_preview",
        "file_size_bytes",
        "render_duration_sec",
        "last_error",
    )
    fields = (
        "format",
        "status",
        "video_preview",
        "file_size_bytes",
        "render_duration_sec",
        "last_error",
    )

    @display(description="Video")
    def video_preview(self, obj: ClipRender) -> str:
        if not obj.video_file:
            return "—"
        url = obj.video_file.url
        return format_html(
            '<video src="{}" controls style="max-width:320px;max-height:180px;"></video>'
            '<br><a href="{}" download>Download</a>',
            url,
            url,
        )


class ClipCandidateInline(TabularInline):
    model = ClipCandidate
    extra = 0
    readonly_fields = (
        "title",
        "hook_text",
        "relevance_score",
        "start_sec",
        "end_sec",
        "reason",
        "status",
        "approved",
        "renders_preview",
    )
    fields = (
        "title",
        "start_sec",
        "end_sec",
        "relevance_score",
        "status",
        "approved",
        "renders_preview",
    )
    ordering = ["-relevance_score"]
    can_delete = False

    @display(description="Renders")
    def renders_preview(self, obj: ClipCandidate) -> str:
        renders = obj.renders.filter(status=ClipRender.RenderStatus.COMPLETED, video_file__isnull=False)
        if not renders.exists():
            return "—"
        return format_html_join(
            " | ",
            '<a href="{}" download>{}</a>',
            ((r.video_file.url, r.get_format_display()) for r in renders),
        )


@admin.register(ClippingJob)
class ClippingJobAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "channel",
        "status_badge",
        "candidates_count",
        "total_cost_display",
        "created_at",
    )
    list_filter = ("status", "source_type", "channel")
    search_fields = ("source_title", "source_url", "channel__name")
    readonly_fields = (
        "id",
        "status",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "failed_at",
        "transcript_text",
        "total_cost_usd",
    )
    inlines = [ClipCandidateInline]

    @display(
        description="Status",
        ordering="status",
        label={
            "INITIALIZING": "default",
            "DOWNLOADING": "info",
            "TRANSCRIBING": "info",
            "ANALYZING": "info",
            "AWAITING_CLIP_APPROVAL": "warning",
            "RENDERING": "info",
            "DISTRIBUTING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "PAUSED": "warning",
        },
    )
    def status_badge(self, obj: ClippingJob) -> str:
        return obj.status

    @display(description="Candidates")
    def candidates_count(self, obj: ClippingJob) -> int:
        return obj.candidates.count()

    @display(description="Total Cost")
    def total_cost_display(self, obj: ClippingJob) -> str:
        return f"${obj.total_cost_usd:.4f}"

    @admin.action(description="Start clipping job (begin download)")
    def start_clipping_job(self, request: HttpRequest, queryset) -> None:
        from reelforge.clipping.tasks import download_source_video

        started = 0
        skipped = 0
        for job in queryset:
            if can_proceed(job.begin_download):
                try:
                    job.begin_download()
                    job.save(update_fields=["status", "started_at", "updated_at"])
                    download_source_video.delay(str(job.id))
                    started += 1
                except TransitionNotAllowed as exc:
                    logger.warning(
                        "Cannot begin download",
                        extra={"job_id": str(job.id), "error": str(exc)},
                    )
                    skipped += 1
            else:
                skipped += 1
        if started:
            self.message_user(request, f"Started {started} clipping job(s).", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} job(s) — not in INITIALIZING state.",
                messages.WARNING,
            )

    @admin.action(description="Retry transcription for stuck/failed jobs")
    def retry_transcription(self, request: HttpRequest, queryset) -> None:
        from reelforge.clipping.tasks import transcribe_video

        retried = 0
        skipped = 0
        for job in queryset:
            if job.status in (ClippingJob.Status.TRANSCRIBING, ClippingJob.Status.FAILED):
                if job.status == ClippingJob.Status.FAILED:
                    try:
                        job.retry_transcription()
                        job.save(update_fields=["status", "last_error", "updated_at"])
                    except TransitionNotAllowed as exc:
                        logger.warning(
                            "Cannot reset job to transcribing",
                            extra={"job_id": str(job.id), "error": str(exc)},
                        )
                        skipped += 1
                        continue
                transcribe_video.delay(str(job.id))
                retried += 1
            else:
                skipped += 1
        if retried:
            self.message_user(request, f"Queued transcription for {retried} job(s).", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} job(s) — must be in TRANSCRIBING or FAILED state.",
                messages.WARNING,
            )

    @admin.action(description="Approve selected candidates")
    def approve_selected_candidates(self, request: HttpRequest, queryset) -> None:
        from django.utils import timezone

        approved = 0
        for candidate in ClipCandidate.objects.filter(clipping_job__in=queryset):
            if candidate.status == ClipCandidate.CandidateStatus.PROPOSED:
                candidate.approved = True
                candidate.status = ClipCandidate.CandidateStatus.APPROVED
                candidate.approved_by = request.user
                candidate.approved_at = timezone.now()
                candidate.save(update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"])
                approved += 1
        self.message_user(request, f"Approved {approved} candidate(s).", messages.SUCCESS)

    @admin.action(description="Trigger rendering for approved candidates")
    def trigger_render(self, request: HttpRequest, queryset) -> None:
        from reelforge.clipping.tasks import render_clip

        triggered = 0
        for job in queryset:
            for candidate in job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED):
                render_clip.delay(str(candidate.id))
                candidate.status = ClipCandidate.CandidateStatus.RENDERING
                candidate.save(update_fields=["status", "updated_at"])
                triggered += 1

            if can_proceed(job.begin_rendering):
                try:
                    job.begin_rendering()
                    job.save(update_fields=["status", "updated_at"])
                except TransitionNotAllowed as exc:
                    logger.warning(
                        "Cannot begin rendering",
                        extra={"job_id": str(job.id), "error": str(exc)},
                    )

        self.message_user(request, f"Triggered rendering for {triggered} candidate(s).", messages.SUCCESS)

    actions = ["start_clipping_job", "retry_transcription", "approve_selected_candidates", "trigger_render"]


@admin.register(ClipPost)
class ClipPostAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "platform_badge",
        "status_badge",
        "views",
        "revenue_est_usd",
        "posted_at",
    )
    list_filter = ("status", "social_account__platform")
    search_fields = ("platform_post_id", "social_account__handle")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "platform_post_id",
        "platform_url",
        "views",
        "likes",
        "comments",
        "shares",
        "revenue_est_usd",
        "last_analytics_sync",
    )

    @display(
        description="Platform",
        label={
            "YOUTUBE": "danger",
            "TIKTOK": "default",
            "INSTAGRAM": "info",
        },
    )
    def platform_badge(self, obj: ClipPost) -> str:
        return obj.social_account.platform

    @display(
        description="Status",
        label={
            "PENDING": "default",
            "POSTING": "info",
            "POSTED": "success",
            "FAILED": "danger",
            "SCHEDULED": "warning",
        },
    )
    def status_badge(self, obj: ClipPost) -> str:
        return obj.status


@admin.register(ClipCandidate)
class ClipCandidateAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "clipping_job",
        "relevance_score",
        "status",
        "approved",
    )
    list_filter = ("status", "approved")
    search_fields = ("title", "clipping_job__source_title")
    readonly_fields = (
        "id",
        "clipping_job",
        "start_sec",
        "end_sec",
        "title",
        "hook_text",
        "relevance_score",
        "reason",
        "transcript_excerpt",
        "status",
        "approved",
        "approved_at",
        "approved_by",
        "created_at",
        "updated_at",
    )
    inlines = [ClipRenderInline]


__all__ = [
    "ClipCandidateAdmin",
    "ClipCandidateInline",
    "ClipPostAdmin",
    "ClipRenderInline",
    "ClippingJobAdmin",
]
