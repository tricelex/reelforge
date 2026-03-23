from __future__ import annotations

import logging

from django.contrib import admin
from django.contrib import messages
from django.http import HttpRequest
from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRender
from reelforge.clipping.models import ClippingJob

logger = logging.getLogger("reelforge.clipping")


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
    )
    fields = (
        "title",
        "start_sec",
        "end_sec",
        "relevance_score",
        "status",
        "approved",
    )
    ordering = ["-relevance_score"]
    can_delete = False


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
                candidate.save(
                    update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"]
                )
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

        self.message_user(
            request, f"Triggered rendering for {triggered} candidate(s).", messages.SUCCESS
        )

    actions = ["approve_selected_candidates", "trigger_render"]


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


# ClipRender is intentionally not registered — managed via inline or read-only
__all__ = [
    "ClipCandidateInline",
    "ClippingJobAdmin",
    "ClipPostAdmin",
    "ClipRender",
]
