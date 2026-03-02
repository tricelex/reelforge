from __future__ import annotations

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.decorators import display

from ***REMOVED***.core.admin import FSMModelAdminMixin
from ***REMOVED***.research.models import ResearchJob
from ***REMOVED***.research.models import TopicIdea


@admin.register(ResearchJob)
class ResearchJobAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "channel",
        "status_badge",
        "trigger_source",
        "topics_discovered",
        "approval_rate_display",
        "created_at",
        "duration_display",
        "cost_display",
    ]
    list_filter = [
        "status",
        "trigger_source",
        "max_competition",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "search_keywords",
        "channel__name",
        "channel__slug",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "duration_seconds",
        "celery_task_id",
        "agent_run_id",
        "agent_tokens_used",
        "agent_cost_usd",
        "approval_rate",
        "trend_data_raw",
        "competitor_data_raw",
        "gap_analysis_raw",
    ]
    autocomplete_fields = ["channel"]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "status",
                    "trigger_source",
                ),
            },
        ),
        (
            _("Research Configuration"),
            {
                "fields": (
                    "search_keywords",
                    "competitors_analyzed",
                    "min_search_volume",
                    "max_competition",
                ),
            },
        ),
        (
            _("Results"),
            {
                "fields": (
                    "topics_discovered",
                    "topics_approved",
                    "topics_rejected",
                    "approval_rate",
                ),
            },
        ),
        (
            _("Raw Research Data"),
            {
                "classes": ("collapse",),
                "fields": (
                    "trend_data_raw",
                    "competitor_data_raw",
                    "gap_analysis_raw",
                ),
            },
        ),
        (
            _("Agent Execution"),
            {
                "classes": ("collapse",),
                "fields": (
                    "agent_run_id",
                    "agent_tokens_used",
                    "agent_cost_usd",
                ),
            },
        ),
        (
            _("Timeline"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "started_at",
                    "completed_at",
                    "duration_seconds",
                ),
            },
        ),
        (
            _("Error Tracking"),
            {
                "classes": ("collapse",),
                "fields": (
                    "retry_count",
                    "max_retries",
                    "last_error",
                    "error_trace",
                    "celery_task_id",
                ),
            },
        ),
        (
            _("Notes"),
            {
                "classes": ("collapse",),
                "fields": ("notes",),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            "PENDING": "default",
            "QUEUED": "info",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "RETRYING": "warning",
            "PAUSED": "warning",
            "REJECTED": "default",
            "SKIPPED": "default",
        },
    )
    def status_badge(self, obj: ResearchJob) -> str:
        return obj.status

    @display(description=_("Approval Rate"), ordering="topics_approved")
    def approval_rate_display(self, obj: ResearchJob) -> str:
        return f"{obj.approval_rate:.1f}%"

    @display(description=_("Duration"))
    def duration_display(self, obj: ResearchJob) -> str:
        if obj.duration_seconds:
            return f"{obj.duration_seconds}s"
        return "-"

    @display(description=_("Cost"), ordering="agent_cost_usd")
    def cost_display(self, obj: ResearchJob) -> str:
        return f"${obj.agent_cost_usd:.4f}"


@admin.register(TopicIdea)
class TopicIdeaAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "title_idea",
        "channel",
        "status_badge",
        "approved",
        "opportunity_score_bar",
        "trend_direction",
        "competition_level",
        "created_at",
    ]
    list_filter = [
        "status",
        "approved",
        "trend_direction",
        "competition_level",
        "approval_source",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "title_idea",
        "description",
        "keywords",
        "channel__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "duration_seconds",
        "celery_task_id",
        "agent_run_id",
        "agent_tokens_used",
        "agent_cost_usd",
        "combined_score",
        "approved_at",
    ]
    autocomplete_fields = ["channel", "research_job", "approved_by"]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "research_job",
                    "status",
                ),
            },
        ),
        (
            _("Topic Content"),
            {
                "fields": (
                    "title_idea",
                    "description",
                    "angle",
                    "keywords",
                ),
            },
        ),
        (
            _("Research Metrics"),
            {
                "fields": (
                    "estimated_search_volume",
                    "competition_level",
                    "trend_direction",
                    "trend_score",
                    "gap_opportunity_score",
                    "combined_score",
                ),
            },
        ),
        (
            _("Gap Analysis"),
            {
                "classes": ("collapse",),
                "fields": (
                    "competitor_video_count",
                    "avg_competitor_views",
                ),
            },
        ),
        (
            _("Content Hints from Research"),
            {
                "classes": ("collapse",),
                "fields": (
                    "thumbnail_concept",
                    "why_it_works",
                    "suggested_sources",
                    "community_questions",
                ),
            },
        ),
        (
            _("Approval"),
            {
                "fields": (
                    "approved",
                    "approved_at",
                    "approved_by",
                    "approval_source",
                    "rejection_reason",
                ),
            },
        ),
        (
            _("Timeline"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "started_at",
                    "completed_at",
                    "duration_seconds",
                ),
            },
        ),
        (
            _("Notes"),
            {
                "classes": ("collapse",),
                "fields": ("notes",),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            "PENDING": "default",
            "QUEUED": "info",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "RETRYING": "warning",
            "PAUSED": "warning",
            "REJECTED": "default",
            "SKIPPED": "default",
        },
    )
    def status_badge(self, obj: TopicIdea) -> str:
        return obj.status

    @display(description=_("Score"), ordering="trend_score")
    def combined_score_display(self, obj: TopicIdea) -> str:
        return f"{obj.combined_score:.1f}/10"

    @display(description=_("Opportunity"))
    def opportunity_score_bar(self, obj: TopicIdea) -> str:
        """Visual opportunity score bar."""
        score = obj.combined_score  # 0-10 scale
        color = "#4CAF50" if score > 7 else "#FF9800" if score > 4 else "#F44336"
        # Convert to percentage for 100px bar
        width = int(score * 10)  # 0-100
        return format_html(
            '<div style="background:#eee;border-radius:3px;width:100px">'
            '<div style="background:{};width:{}px;height:12px;border-radius:3px"></div>'
            "</div> {}",
            color,
            width,
            f"{score:.0f}",
        )

    # ── Admin Actions ──────────────────────────────────────────────────

    @action(description="✅ Approve Selected")
    def approve_selected(self, request, queryset) -> None:
        """Approve selected topic ideas."""
        count = queryset.update(approved=True, approved_at=timezone.now())
        self.message_user(request, f"{count} topics approved.")

    @action(description="❌ Reject Selected")
    def reject_selected(self, request, queryset) -> None:
        """Reject selected topic ideas."""
        count = queryset.update(approved=False, rejection_reason="Rejected by operator")
        self.message_user(request, f"{count} topics rejected.")

    @action(description="📝 Trigger Scripting")
    def trigger_scripting(self, request, queryset) -> None:
        """Trigger script jobs for approved topics."""
        # TODO: Implement when scripts.tasks exists
        # from ***REMOVED***.scripts.tasks import create_script_job
        count = 0
        for _topic in queryset.filter(approved=True):
            # create_script_job.delay(str(topic.id))
            count += 1
        self.message_user(request, f"Scripting will be triggered for {count} topics.")
