from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from ***REMOVED***.pipeline.models import PipelineEvent
from ***REMOVED***.pipeline.models import PipelineRun

if TYPE_CHECKING:
    from django.http import HttpRequest


class PipelineEventInline(TabularInline):
    model = PipelineEvent
    extra = 0
    fields = [
        "event_type",
        "event_name",
        "message",
        "triggered_by_user",
        "triggered_by_agent",
        "created_at",
    ]
    readonly_fields = fields
    ordering = ["created_at"]

    def has_add_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PipelineRun | None = None) -> bool:
        return False


@admin.register(PipelineRun)
class PipelineRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel",
        "overall_status_badge",
        "final_video_title",
        "video_link",
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

    @display(description=_("Video Link"))
    def video_link(self, obj: PipelineRun) -> str:
        if obj.final_video_url:
            return format_html(
                '<a href="{}" target="_blank">Watch</a>',
                obj.final_video_url,
            )
        return "-"

    @display(description=_("Total Cost"), ordering="total_agent_cost_usd")
    def total_cost_display(self, obj: PipelineRun) -> str:
        return f"${obj.total_cost_usd:.4f}"

    @display(description=_("Duration"))
    def duration_display(self, obj: PipelineRun) -> str:
        if obj.duration_hours:
            return f"{obj.duration_hours:.1f}h"
        return "-"


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
