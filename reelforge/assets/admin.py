from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from reelforge.assets.models import AssetJob
from reelforge.assets.models import GeneratedImage
from reelforge.assets.models import ThumbnailOption
from reelforge.assets.models import VoiceoverSegment

# ── Inlines ──────────────────────────────────────────────────────────────────


class VoiceoverSegmentInline(TabularInline):
    model = VoiceoverSegment
    extra = 0
    ordering = ["segment_id"]
    fields = ["segment_id", "section", "text_preview", "duration_sec", "status", "audio_file"]
    readonly_fields = ["text_preview", "duration_sec", "audio_file", "status"]

    @admin.display(description=_("Script Text"))
    def text_preview(self, obj: VoiceoverSegment) -> str:
        return obj.text[:100] + "..." if len(obj.text) > 100 else obj.text


class GeneratedImageInline(TabularInline):
    model = GeneratedImage
    extra = 0
    ordering = ["position_idx"]
    fields = ["position_idx", "section", "prompt_preview", "is_selected", "image_file", "provider"]
    readonly_fields = ["prompt_preview", "image_file", "provider"]

    @admin.display(description=_("Prompt"))
    def prompt_preview(self, obj: GeneratedImage) -> str:
        return obj.prompt_used[:80] + "..." if len(obj.prompt_used) > 80 else obj.prompt_used


class ThumbnailOptionInline(TabularInline):
    model = ThumbnailOption
    extra = 0
    ordering = ["option_number"]
    fields = ["option_number", "image_file", "ctr_score", "is_selected"]
    readonly_fields = ["option_number", "image_file", "ctr_score"]


# ── Admin Classes ────────────────────────────────────────────────────────────


@admin.register(AssetJob)
class AssetJobAdmin(ModelAdmin):
    list_display = [
        "id",
        "script_job_link",
        "channel_name",
        "status_badge",
        "voiceover_duration_display",
        "images_count_display",
        "cost_display",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "id",
        "script_job__final_title",
        "script_job__topic__title_idea",
        "script_job__topic__channel__name",
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
        "voiceover_duration_sec",
        "total_images_count",
    ]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    inlines = [VoiceoverSegmentInline, GeneratedImageInline, ThumbnailOptionInline]

    fieldsets = [
        (
            _("Basic Information"),
            {
                "fields": [
                    "id",
                    "script_job",
                    "status",
                ],
            },
        ),
        (
            _("Voiceover"),
            {
                "fields": [
                    "voiceover_status",
                    "voiceover_provider",
                    "voiceover_duration_sec",
                    "voiceover_full_file",
                    "voiceover_cost_usd",
                ],
            },
        ),
        (
            _("Music"),
            {
                "fields": [
                    "music_status",
                    "music_style",
                    "music_file",
                    "music_volume_pct",
                ],
            },
        ),
        (
            _("Images"),
            {
                "fields": [
                    "images_status",
                    "images_provider",
                    "images_count",
                    "images_cost_usd",
                ],
            },
        ),
        (
            _("Thumbnails"),
            {
                "fields": [
                    "thumbnails_status",
                    "selected_thumbnail",
                ],
            },
        ),
        (
            _("Timeline & Costs"),
            {
                "classes": ["collapse"],
                "fields": [
                    "visual_timeline",
                    "total_cost_usd",
                ],
            },
        ),
        (
            _("Agent Execution"),
            {
                "classes": ["collapse"],
                "fields": [
                    "celery_task_id",
                    "agent_run_id",
                    "agent_tokens_used",
                    "agent_cost_usd",
                    "retry_count",
                    "max_retries",
                    "last_error",
                    "error_trace",
                ],
            },
        ),
        (
            _("Timeline"),
            {
                "classes": ["collapse"],
                "fields": [
                    "created_at",
                    "updated_at",
                    "started_at",
                    "completed_at",
                    "duration_seconds",
                ],
            },
        ),
        (
            _("Notes"),
            {
                "classes": ["collapse"],
                "fields": ["notes"],
            },
        ),
    ]

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
        },
    )
    def status_badge(self, obj: AssetJob) -> str:
        return obj.status

    @display(description=_("Script Job"), ordering="script_job")
    def script_job_link(self, obj: AssetJob) -> str:
        if obj.script_job:
            title = obj.script_job.final_title or obj.script_job.topic.title_idea
            return format_html(
                '<a href="/admin/scripts/scriptjob/{}/change/">{}</a>',
                obj.script_job.id,
                title[:60],
            )
        return "-"

    @display(description=_("Channel"), ordering="script_job__topic__channel__name")
    def channel_name(self, obj: AssetJob) -> str:
        return obj.channel.name if obj.channel else "-"

    @display(description=_("Voiceover Duration"), ordering="voiceover_duration_sec")
    def voiceover_duration_display(self, obj: AssetJob) -> str:
        if obj.voiceover_duration_sec > 0:
            minutes = int(obj.voiceover_duration_sec // 60)
            seconds = int(obj.voiceover_duration_sec % 60)
            return f"{minutes}:{seconds:02d}"
        return "-"

    @display(description=_("Images"), ordering="total_images_count")
    def images_count_display(self, obj: AssetJob) -> str:
        return str(obj.total_images_count) if obj.total_images_count > 0 else "-"

    @display(description=_("Cost"), ordering="agent_cost_usd")
    def cost_display(self, obj: AssetJob) -> str:
        if obj.agent_cost_usd > 0:
            return f"${obj.agent_cost_usd:.4f}"
        return "$0.0000"


@admin.register(VoiceoverSegment)
class VoiceoverSegmentAdmin(ModelAdmin):
    list_display = ["asset_job", "segment_id", "section", "text_preview", "duration_sec", "status"]
    list_filter = ["status", "section", "tts_provider_used", "created_at"]
    search_fields = ["asset_job__id", "text"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["asset_job", "segment_id"]

    @admin.display(description=_("Script Text"))
    def text_preview(self, obj: VoiceoverSegment) -> str:
        return obj.text[:100] + "..." if len(obj.text) > 100 else obj.text


@admin.register(GeneratedImage)
class GeneratedImageAdmin(ModelAdmin):
    list_display = ["asset_job", "position_idx", "section", "is_selected", "prompt_preview", "provider"]
    list_filter = ["is_selected", "section", "provider", "created_at"]
    search_fields = ["asset_job__id", "prompt_used", "section"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["asset_job", "position_idx"]

    @admin.display(description=_("Prompt"))
    def prompt_preview(self, obj: GeneratedImage) -> str:
        return obj.prompt_used[:80] + "..." if len(obj.prompt_used) > 80 else obj.prompt_used


@admin.register(ThumbnailOption)
class ThumbnailOptionAdmin(ModelAdmin):
    list_display = ["asset_job", "option_number", "ctr_score", "is_selected", "prompt_preview"]
    list_filter = ["is_selected", "created_at"]
    search_fields = ["asset_job__id", "prompt_used"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["asset_job", "-ctr_score"]

    @admin.display(description=_("Prompt"))
    def prompt_preview(self, obj: ThumbnailOption) -> str:
        return obj.prompt_used[:80] + "..." if len(obj.prompt_used) > 80 else obj.prompt_used
