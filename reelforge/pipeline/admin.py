from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_fsm import can_proceed
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import action
from unfold.decorators import display

from ***REMOVED***.pipeline.models import PipelineEvent
from ***REMOVED***.pipeline.models import PipelineRun

if TYPE_CHECKING:
    from django.http import HttpRequest


class PipelineEventInline(TabularInline):
    model = PipelineEvent
    extra = 0
    fields = [
        "created_at",
        "event_type_badge",
        "event_name",
        "message",
        "triggered_by_agent",
    ]
    readonly_fields = ["created_at", "event_type_badge", "event_name", "message", "triggered_by_agent"]
    ordering = ["created_at"]

    def has_add_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    @display(
        description=_("Type"),
        label={
            "INFO": "info",
            "SUCCESS": "success",
            "WARNING": "warning",
            "ERROR": "danger",
            "RETRY": "warning",
            "MANUAL": "default",
        },
    )
    def event_type_badge(self, obj: PipelineEvent) -> str:
        return obj.event_type


@admin.register(PipelineRun)
class PipelineRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel",
        "stage_progress",
        "overall_status_badge",
        "pipeline_title",
        "youtube_link",
        "thumbnail_preview_display",
        "total_cost_display",
        "duration_display",
        "created_at",
    ]
    list_filter = [
        "overall_status",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "final_video_title",
        "channel__name",
        "orchestrator_run_id",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "failed_at",
        "orchestrator_turns",
        "total_agent_cost_usd",
        "total_asset_cost_usd",
        "total_cost_usd",
        "final_video_url",
        "final_video_duration_seconds",
        "duration_hours",
        "available_transitions",
        "fsm_actions_display",
    ]
    autocomplete_fields = [
        "channel",
        "research_job",
        "topic",
        "script_job",
        "asset_job",
        "production_job",
        "distribution_job",
    ]
    inlines = [PipelineEventInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "overall_status",
                    "available_transitions",
                ),
            },
        ),
        (
            _("Stage Job Links"),
            {
                "fields": (
                    "research_job",
                    "topic",
                    "script_job",
                    "asset_job",
                    "production_job",
                    "distribution_job",
                ),
            },
        ),
        (
            _("Orchestrator Context"),
            {
                "classes": ("collapse",),
                "fields": (
                    "orchestrator_run_id",
                    "orchestrator_turns",
                    "last_agent_decision",
                ),
            },
        ),
        (
            _("Costs"),
            {
                "fields": (
                    "total_agent_cost_usd",
                    "total_asset_cost_usd",
                    "total_cost_usd",
                ),
            },
        ),
        (
            _("Final Video Info"),
            {
                "fields": (
                    "final_video_title",
                    "final_video_url",
                    "final_video_duration_seconds",
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
                    "failed_at",
                    "duration_hours",
                ),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="overall_status",
        label={
            "INITIALIZING": "default",
            "RESEARCHING": "info",
            "SCRIPTING": "info",
            "AWAITING_APPROVAL": "warning",
            "GENERATING_ASSETS": "info",
            "RENDERING": "info",
            "QA": "info",
            "UPLOADING": "info",
            "PUBLISHED": "success",
            "FAILED": "danger",
            "PAUSED": "warning",
        },
    )
    def overall_status_badge(self, obj: PipelineRun) -> str:
        return obj.overall_status

    @display(description=_("Title"))
    def pipeline_title(self, obj: PipelineRun) -> str:
        """Display run title from final_video_title or topic."""
        return obj.final_video_title or (obj.topic.title_idea[:60] if obj.topic else "Untitled")

    @display(description=_("Pipeline Progress"))
    def stage_progress(self, obj: PipelineRun) -> str:
        """Visual progress indicator with filled/empty circles."""
        stages = ["RESEARCHING", "SCRIPTING", "GENERATING_ASSETS", "RENDERING", "QA", "UPLOADING", "PUBLISHED"]
        current_idx = stages.index(obj.current_stage) if obj.current_stage in stages else -1
        filled = "●" * (current_idx + 1)
        empty = "○" * (len(stages) - current_idx - 1)
        return format_html(
            '<span style="font-family:monospace;color:#4CAF50">{}</span>'
            '<span style="font-family:monospace;color:#ccc">{}</span> {}/{}',
            filled,
            empty,
            max(current_idx + 1, 0),
            len(stages),
        )

    @display(description=_("YouTube"))
    def youtube_link(self, obj: PipelineRun) -> str:
        """YouTube video link with play icon."""
        if obj.final_video_url:
            return format_html('<a href="{}" target="_blank">▶ Watch</a>', obj.final_video_url)
        return "—"

    @display(description=_("Thumbnail"))
    def thumbnail_preview_display(self, obj: PipelineRun) -> str:
        """Thumbnail image preview."""
        if obj.asset_job and obj.asset_job.selected_thumbnail:
            return format_html(
                '<img src="{}" style="max-height:80px;border-radius:4px">',
                obj.asset_job.selected_thumbnail.url,
            )
        return "—"

    @display(description=_("Total Cost"), ordering="total_agent_cost_usd")
    def total_cost_display(self, obj: PipelineRun) -> str:
        return f"${obj.total_cost_usd:.4f}"

    @display(description=_("Duration"))
    def duration_display(self, obj: PipelineRun) -> str:
        if obj.duration_hours:
            return f"{obj.duration_hours:.1f}h"
        return "-"

    @display(description=_("Available Actions"))
    def fsm_actions_display(self, obj: PipelineRun) -> str:
        """Show what FSM transitions are available for this run — always accurate."""
        transitions = obj.available_transitions
        if not transitions:
            return "—"
        badges = " ".join(
            f'<span style="background:#e0e0e0;padding:2px 6px;border-radius:3px;font-size:11px">{t}</span>'
            for t in transitions
        )
        return format_html(badges)

    # ── Admin Actions ──────────────────────────────────────────────────

    @action(description="▶ Approve & Continue to Assets")
    def approve_to_assets(self, request, queryset) -> None:
        """Only valid when run is in AWAITING_APPROVAL state."""
        count = 0
        for run in queryset:
            if can_proceed(run.begin_assets):  # FSM checks validity
                run.begin_assets()  # Triggers post_transition signal → Celery task
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot approve '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} runs approved and advancing to asset generation.")

    @action(description="🔄 Retry Rendering")
    def retry_rendering_action(self, request, queryset) -> None:
        """Retry rendering for failed pipelines."""
        count = 0
        for run in queryset:
            if can_proceed(run.retry_rendering):
                run.retry_rendering()
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot retry rendering for '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} runs set to retry rendering.")

    @action(description="⏸ Pause Pipeline")
    def pause_action(self, request, queryset) -> None:
        """Pause pipelines for manual intervention."""
        count = 0
        for run in queryset:
            if can_proceed(run.pause_pipeline):
                run.pause_pipeline(reason="Manually paused by operator")
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot pause '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} pipelines paused.")

    @action(description="🗑 Reject & Archive")
    def reject_run(self, request, queryset) -> None:
        """Reject and archive pipeline runs."""
        count = 0
        for run in queryset:
            if can_proceed(run.mark_failed):
                run.mark_failed(reason="Rejected by operator")
                run.save()
                count += 1
            else:
                self.message_user(
                    request,
                    f"Cannot reject '{run}' — current state: {run.overall_status}",
                    level="ERROR",
                )
        if count > 0:
            self.message_user(request, f"{count} runs rejected.")


@admin.register(PipelineEvent)
class PipelineEventAdmin(ModelAdmin):
    list_display = [
        "id",
        "pipeline_run",
        "event_type_badge",
        "event_name",
        "message_preview",
        "triggered_by_user",
        "triggered_by_agent",
        "created_at",
    ]
    list_filter = [
        "event_type",
        "created_at",
        "triggered_by_agent",
    ]
    search_fields = [
        "id",
        "event_name",
        "message",
        "pipeline_run__id",
        "pipeline_run__final_video_title",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "pipeline_run",
        "event_type",
        "event_name",
        "message",
        "metadata",
        "triggered_by_user",
        "triggered_by_agent",
    ]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "pipeline_run",
                    "event_type",
                    "event_name",
                ),
            },
        ),
        (
            _("Event Details"),
            {
                "fields": (
                    "message",
                    "metadata",
                ),
            },
        ),
        (
            _("Attribution"),
            {
                "fields": (
                    "triggered_by_user",
                    "triggered_by_agent",
                ),
            },
        ),
        (
            _("Timestamps"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: PipelineEvent | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PipelineEvent | None = None) -> bool:
        return False

    @display(
        description=_("Event Type"),
        ordering="event_type",
        label={
            "INFO": "info",
            "SUCCESS": "success",
            "WARNING": "warning",
            "ERROR": "danger",
            "RETRY": "warning",
            "MANUAL": "default",
        },
    )
    def event_type_badge(self, obj: PipelineEvent) -> str:
        return obj.event_type

    @display(description=_("Message"))
    def message_preview(self, obj: PipelineEvent) -> str:
        return obj.message[:100]
