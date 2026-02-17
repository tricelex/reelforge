from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from reelforge.assets.models import AssetJob
from reelforge.assets.models import GeneratedImage
from reelforge.assets.models import ThumbnailOption
from reelforge.assets.models import VoiceoverSegment


class VoiceoverSegmentInline(TabularInline):
    model = VoiceoverSegment
    extra = 0
    fields = [
        "segment_index",
        "section",
        "text",
        "duration_seconds",
        "start_ms",
        "end_ms",
        "status",
        "cost_usd",
    ]
    readonly_fields = ["segment_index", "duration_seconds", "start_ms", "end_ms", "cost_usd"]
    ordering = ["segment_index"]


class GeneratedImageInline(TabularInline):
    model = GeneratedImage
    extra = 0
    fields = [
        "position_index",
        "section",
        "timestamp_approx",
        "prompt",
        "is_selected",
        "animation_type",
        "duration_seconds",
        "status",
        "cost_usd",
    ]
    readonly_fields = ["position_index", "cost_usd"]
    ordering = ["position_index"]


class ThumbnailOptionInline(TabularInline):
    model = ThumbnailOption
    extra = 0
    fields = [
        "option_number",
        "prompt",
        "is_selected",
        "ctr_score",
        "status",
        "cost_usd",
    ]
    readonly_fields = ["option_number", "ctr_score", "cost_usd"]
    ordering = ["option_number"]


@admin.register(AssetJob)
class AssetJobAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel",
        "status_badge",
        "voiceover_status_badge",
        "images_status_badge",
        "thumbnails_status_badge",
        "total_cost_display",
        "created_at",
    ]
    list_filter = [
        "status",
        "voiceover_status",
        "images_status",
        "thumbnails_status",
        "created_at",
        "channel",
    ]
    search_fields = [
        "id",
        "script_job__final_title",
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
        "total_cost_usd",
        "all_assets_ready",
        "voiceover_provider",
        "voiceover_duration_seconds",
        "images_provider",
        "images_generated_count",
        "thumbnails_generated_count",
        "visual_timeline",
    ]
    autocomplete_fields = ["channel", "script_job"]
    inlines = [VoiceoverSegmentInline, GeneratedImageInline, ThumbnailOptionInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "script_job",
                    "status",
                    "all_assets_ready",
                ),
            },
        ),
        (
            _("Voiceover"),
            {
                "fields": (
                    "voiceover_provider",
                    "voiceover_status",
                    "voiceover_file",
                    "voiceover_duration_seconds",
                    "voiceover_cost_usd",
                ),
            },
        ),
        (
            _("Images"),
            {
                "fields": (
                    "images_provider",
                    "images_status",
                    "images_generated_count",
                    "images_cost_usd",
                ),
            },
        ),
        (
            _("Music"),
            {
                "classes": ("collapse",),
                "fields": (
                    "music_file",
                    "music_url",
                    "music_title",
                    "music_style",
                    "music_volume_pct",
                    "music_status",
                ),
            },
        ),
        (
            _("Thumbnails"),
            {
                "fields": (
                    "thumbnails_status",
                    "thumbnails_generated_count",
                    "selected_thumbnail",
                    "thumbnails_cost_usd",
                ),
            },
        ),
        (
            _("Visual Timeline (Master Coordination)"),
            {
                "classes": ("collapse",),
                "fields": ("visual_timeline",),
            },
        ),
        (
            _("Cost Summary"),
            {
                "fields": ("total_cost_usd",),
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
    def status_badge(self, obj: AssetJob) -> str:
        return obj.status

    @display(
        description=_("Voiceover"),
        ordering="voiceover_status",
        label={
            "PENDING": "default",
            "GENERATING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def voiceover_status_badge(self, obj: AssetJob) -> str:
        return obj.voiceover_status

    @display(
        description=_("Images"),
        ordering="images_status",
        label={
            "PENDING": "default",
            "GENERATING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def images_status_badge(self, obj: AssetJob) -> str:
        return obj.images_status

    @display(
        description=_("Thumbnails"),
        ordering="thumbnails_status",
        label={
            "PENDING": "default",
            "GENERATING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def thumbnails_status_badge(self, obj: AssetJob) -> str:
        return obj.thumbnails_status

    @display(description=_("Total Cost"))
    def total_cost_display(self, obj: AssetJob) -> str:
        return f"${obj.total_cost_usd:.4f}"


@admin.register(VoiceoverSegment)
class VoiceoverSegmentAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "segment_index",
        "section",
        "status",
        "duration_seconds",
        "timing_display",
        "cost_display",
    ]
    list_filter = ["status", "section", "tts_provider"]
    search_fields = ["id", "text", "section", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "duration_seconds", "start_ms", "end_ms"]
    autocomplete_fields = ["asset_job"]

    @display(description=_("Timing"))
    def timing_display(self, obj: VoiceoverSegment) -> str:
        if obj.start_ms and obj.end_ms:
            return f"{obj.start_ms}ms - {obj.end_ms}ms"
        return "-"

    @display(description=_("Cost"), ordering="cost_usd")
    def cost_display(self, obj: VoiceoverSegment) -> str:
        return f"${obj.cost_usd:.4f}"


@admin.register(GeneratedImage)
class GeneratedImageAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "position_index",
        "section",
        "timestamp_approx",
        "is_selected",
        "status",
        "animation_type",
        "cost_display",
    ]
    list_filter = ["status", "is_selected", "section", "animation_type", "image_provider"]
    search_fields = ["id", "prompt", "section", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["asset_job"]

    @display(description=_("Cost"), ordering="cost_usd")
    def cost_display(self, obj: GeneratedImage) -> str:
        return f"${obj.cost_usd:.4f}"


@admin.register(ThumbnailOption)
class ThumbnailOptionAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "option_number",
        "is_selected",
        "ctr_score_display",
        "status",
        "cost_display",
    ]
    list_filter = ["status", "is_selected", "image_provider"]
    search_fields = ["id", "prompt", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "ctr_score"]
    autocomplete_fields = ["asset_job"]

    @display(description=_("CTR Score"), ordering="ctr_score")
    def ctr_score_display(self, obj: ThumbnailOption) -> str:
        return f"{obj.ctr_score:.1f}/10"

    @display(description=_("Cost"), ordering="cost_usd")
    def cost_display(self, obj: ThumbnailOption) -> str:
        return f"${obj.cost_usd:.4f}"
