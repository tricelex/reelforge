from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from reelforge.core.admin import FSMModelAdminMixin
from reelforge.production.models import ProductionJob


@admin.register(ProductionJob)
class ProductionJobAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "id",
        "channel",
        "status_badge",
        "render_engine",
        "qa_passed",
        "qa_pass_rate_display",
        "has_shorts",
        "video_duration_display",
        "file_size_display",
        "created_at",
        "render_time_display",
    ]
    list_filter = [
        "status",
        "render_engine",
        "qa_passed",
        "resolution",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "asset_job__script_job__final_title",
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
        "video_duration_sec",
        "file_size_bytes",
        "file_size_mb",
        "bitrate_kbps",
        "qa_checks_run",
        "qa_checks_passed",
        "qa_pass_rate",
        "render_duration_sec",
        "has_shorts",
        "shorts_duration_sec",
    ]
    autocomplete_fields = ["channel", "asset_job"]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "asset_job",
                    "status",
                ),
            },
        ),
        (
            _("Render Configuration"),
            {
                "fields": (
                    "render_engine",
                    "render_spec",
                    "resolution",
                    "fps",
                    "codec",
                    "crf",
                ),
            },
        ),
        (
            _("Output Files"),
            {
                "fields": (
                    "raw_video_file",
                    "processed_video_file",
                    "shorts_video_file",
                ),
            },
        ),
        (
            _("Video Metadata"),
            {
                "fields": (
                    "video_duration_sec",
                    "file_size_bytes",
                    "file_size_mb",
                    "bitrate_kbps",
                ),
            },
        ),
        (
            _("QA Results"),
            {
                "fields": (
                    "qa_passed",
                    "qa_checks_run",
                    "qa_checks_passed",
                    "qa_pass_rate",
                    "qa_results",
                    "qa_notes",
                ),
            },
        ),
        (
            _("Shorts Extraction"),
            {
                "classes": ("collapse",),
                "fields": (
                    "has_shorts",
                    "shorts_start_sec",
                    "shorts_end_sec",
                    "shorts_duration_sec",
                    "shorts_selection_reason",
                ),
            },
        ),
        (
            _("Render Performance"),
            {
                "classes": ("collapse",),
                "fields": (
                    "render_duration_sec",
                    "render_worker_id",
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
    def status_badge(self, obj: ProductionJob) -> str:
        return obj.status

    @display(description=_("QA Pass Rate"), ordering="qa_checks_passed")
    def qa_pass_rate_display(self, obj: ProductionJob) -> str:
        return f"{obj.qa_pass_rate:.1f}%"

    @display(description=_("Video Duration"))
    def video_duration_display(self, obj: ProductionJob) -> str:
        if obj.video_duration_sec:
            minutes = int(obj.video_duration_sec // 60)
            seconds = int(obj.video_duration_sec % 60)
            return f"{minutes}m {seconds}s"
        return "-"

    @display(description=_("File Size"))
    def file_size_display(self, obj: ProductionJob) -> str:
        if obj.file_size_mb:
            return f"{obj.file_size_mb:.1f} MB"
        return "-"

    @display(description=_("Render Time"))
    def render_time_display(self, obj: ProductionJob) -> str:
        if obj.render_duration_sec:
            minutes = int(obj.render_duration_sec // 60)
            seconds = int(obj.render_duration_sec % 60)
            return f"{minutes}m {seconds}s"
        return "-"
