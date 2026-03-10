from __future__ import annotations

from django.contrib import admin
from django.db import transaction
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from ***REMOVED***.assets.models import AssetJob
from ***REMOVED***.assets.models import GeneratedImage
from ***REMOVED***.assets.models import GeneratedVideoClip
from ***REMOVED***.assets.models import ImageGenerationRun
from ***REMOVED***.assets.models import ThumbnailOption
from ***REMOVED***.assets.models import ThumbnailRun
from ***REMOVED***.assets.models import VideoClipGenerationRun
from ***REMOVED***.assets.models import VoiceoverRun
from ***REMOVED***.assets.models import VoiceoverSegment
from ***REMOVED***.core.admin import FSMModelAdminMixin

# ── Run status label map (reused across run admin classes) ────────────────────

_RUN_STATUS_LABELS = {
    "PENDING": "default",
    "RUNNING": "info",
    "COMPLETED": "success",
    "FAILED": "danger",
}

# ── Child inlines (shown inside Run admin detail pages) ───────────────────────


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


class GeneratedVideoClipInline(TabularInline):
    model = GeneratedVideoClip
    extra = 0
    ordering = ["position_idx"]
    fields = ["position_idx", "prompt_preview", "duration_sec", "is_selected", "clip_file", "provider"]
    readonly_fields = ["prompt_preview", "duration_sec", "clip_file", "provider"]

    @admin.display(description=_("Prompt"))
    def prompt_preview(self, obj: GeneratedVideoClip) -> str:
        return obj.prompt_used[:80] + "..." if len(obj.prompt_used) > 80 else obj.prompt_used


# ── Run inlines (shown inside AssetJobAdmin) ──────────────────────────────────


class VoiceoverRunInline(TabularInline):
    model = VoiceoverRun
    extra = 0
    ordering = ["run_number"]
    fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "total_duration_sec",
        "total_cost_usd",
        "completed_at",
    ]
    readonly_fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "total_duration_sec",
        "total_cost_usd",
        "completed_at",
    ]

    @admin.display(description=_("Status"))
    def run_status_badge(self, obj: VoiceoverRun) -> str:
        colors = {"PENDING": "#999", "RUNNING": "#0070f3", "COMPLETED": "#16a34a", "FAILED": "#dc2626"}
        color = colors.get(obj.status, "#999")
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, obj.status)


class ImageGenerationRunInline(TabularInline):
    model = ImageGenerationRun
    extra = 0
    ordering = ["run_number"]
    fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "images_count",
        "total_cost_usd",
        "completed_at",
    ]
    readonly_fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "images_count",
        "total_cost_usd",
        "completed_at",
    ]

    @admin.display(description=_("Status"))
    def run_status_badge(self, obj: ImageGenerationRun) -> str:
        colors = {"PENDING": "#999", "RUNNING": "#0070f3", "COMPLETED": "#16a34a", "FAILED": "#dc2626"}
        color = colors.get(obj.status, "#999")
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, obj.status)


class VideoClipGenerationRunInline(TabularInline):
    model = VideoClipGenerationRun
    extra = 0
    ordering = ["run_number"]
    fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "clips_count",
        "total_cost_usd",
        "completed_at",
    ]
    readonly_fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "clips_count",
        "total_cost_usd",
        "completed_at",
    ]

    @admin.display(description=_("Status"))
    def run_status_badge(self, obj: VideoClipGenerationRun) -> str:
        colors = {"PENDING": "#999", "RUNNING": "#0070f3", "COMPLETED": "#16a34a", "FAILED": "#dc2626"}
        color = colors.get(obj.status, "#999")
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, obj.status)


class ThumbnailRunInline(TabularInline):
    model = ThumbnailRun
    extra = 0
    ordering = ["run_number"]
    fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "options_count",
        "total_cost_usd",
        "completed_at",
    ]
    readonly_fields = [
        "run_number",
        "run_status_badge",
        "provider",
        "options_count",
        "total_cost_usd",
        "completed_at",
    ]

    @admin.display(description=_("Status"))
    def run_status_badge(self, obj: ThumbnailRun) -> str:
        colors = {"PENDING": "#999", "RUNNING": "#0070f3", "COMPLETED": "#16a34a", "FAILED": "#dc2626"}
        color = colors.get(obj.status, "#999")
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, obj.status)


# ── AssetJob Admin ────────────────────────────────────────────────────────────


@admin.register(AssetJob)
class AssetJobAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "id",
        "script_job_link",
        "channel_name",
        "status_badge",
        "voiceover_runs_count",
        "image_runs_count",
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
    inlines = [
        VoiceoverRunInline,
        ImageGenerationRunInline,
        VideoClipGenerationRunInline,
        ThumbnailRunInline,
    ]
    actions = [
        "start_new_voiceover_run",
        "start_new_image_generation_run",
        "start_new_video_clip_run",
        "start_new_thumbnail_run",
    ]

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
            _("Selected Runs"),
            {
                "fields": [
                    "selected_voiceover_run",
                    "selected_image_run",
                    "selected_video_clip_run",
                    "selected_thumbnail_run",
                ],
            },
        ),
        (
            _("Voiceover (rollup)"),
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
            _("Images (rollup)"),
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
            _("Thumbnails (rollup)"),
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

    @display(description=_("Voiceover Runs"))
    def voiceover_runs_count(self, obj: AssetJob) -> str:
        count = obj.voiceover_runs.count()
        return str(count) if count else "-"

    @display(description=_("Image Runs"))
    def image_runs_count(self, obj: AssetJob) -> str:
        count = obj.image_runs.count()
        return str(count) if count else "-"

    @display(description=_("Cost"), ordering="agent_cost_usd")
    def cost_display(self, obj: AssetJob) -> str:
        if obj.agent_cost_usd > 0:
            return f"${obj.agent_cost_usd:.4f}"
        return "$0.0000"

    # ── "Start New Run" admin actions ─────────────────────────────────────────

    @admin.action(description=_("Start new voiceover run"))
    def start_new_voiceover_run(self, request, queryset):
        from django.db.models import Max

        from ***REMOVED***.pipeline.tasks import run_voiceover_run

        for job in queryset:
            next_num = (job.voiceover_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
            run = VoiceoverRun.objects.create(asset_job=job, run_number=next_num)
            transaction.on_commit(lambda run_id=str(run.id): run_voiceover_run.delay(run_id))
        self.message_user(request, _("New voiceover run(s) dispatched."))

    @admin.action(description=_("Start new image generation run"))
    def start_new_image_generation_run(self, request, queryset):
        from django.db.models import Max

        from ***REMOVED***.pipeline.tasks import run_image_generation_run

        for job in queryset:
            next_num = (job.image_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
            run = ImageGenerationRun.objects.create(asset_job=job, run_number=next_num)
            transaction.on_commit(lambda run_id=str(run.id): run_image_generation_run.delay(run_id))
        self.message_user(request, _("New image generation run(s) dispatched."))

    @admin.action(description=_("Start new video clip run (uses selected image run)"))
    def start_new_video_clip_run(self, request, queryset):
        from django.db.models import Max

        from ***REMOVED***.pipeline.tasks import run_video_clip_generation_run

        for job in queryset:
            next_num = (job.video_clip_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
            run = VideoClipGenerationRun.objects.create(
                asset_job=job,
                run_number=next_num,
                image_run=job.selected_image_run,
            )
            transaction.on_commit(lambda run_id=str(run.id): run_video_clip_generation_run.delay(run_id))
        self.message_user(request, _("New video clip run(s) dispatched."))

    @admin.action(description=_("Start new thumbnail run"))
    def start_new_thumbnail_run(self, request, queryset):
        from django.db.models import Max

        from ***REMOVED***.pipeline.tasks import run_thumbnail_run

        for job in queryset:
            next_num = (job.thumbnail_runs.aggregate(m=Max("run_number"))["m"] or 0) + 1
            run = ThumbnailRun.objects.create(asset_job=job, run_number=next_num)
            transaction.on_commit(lambda run_id=str(run.id): run_thumbnail_run.delay(run_id))
        self.message_user(request, _("New thumbnail run(s) dispatched."))


# ── Run Admin Classes ─────────────────────────────────────────────────────────


@admin.register(VoiceoverRun)
class VoiceoverRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "run_number",
        "run_status_badge",
        "provider",
        "total_duration_sec",
        "total_cost_usd",
        "completed_at",
    ]
    list_filter = ["status", "provider", "created_at"]
    search_fields = ["asset_job__id", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "celery_task_id"]
    ordering = ["asset_job", "run_number"]
    inlines = [VoiceoverSegmentInline]
    actions = ["select_as_active_voiceover_run"]

    @display(description=_("Status"), ordering="status", label=_RUN_STATUS_LABELS)
    def run_status_badge(self, obj: VoiceoverRun) -> str:
        return obj.status

    @admin.action(description=_("Select as active voiceover run"))
    def select_as_active_voiceover_run(self, request, queryset):
        for run in queryset.select_related("asset_job"):
            run.asset_job.selected_voiceover_run = run
            run.asset_job.save(update_fields=["selected_voiceover_run", "updated_at"])
        self.message_user(request, _("Selected run(s) set as active."))


@admin.register(ImageGenerationRun)
class ImageGenerationRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "run_number",
        "run_status_badge",
        "provider",
        "images_count",
        "total_cost_usd",
        "completed_at",
    ]
    list_filter = ["status", "provider", "created_at"]
    search_fields = ["asset_job__id", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "celery_task_id"]
    ordering = ["asset_job", "run_number"]
    inlines = [GeneratedImageInline]
    actions = ["select_as_active_image_run"]

    @display(description=_("Status"), ordering="status", label=_RUN_STATUS_LABELS)
    def run_status_badge(self, obj: ImageGenerationRun) -> str:
        return obj.status

    @admin.action(description=_("Select as active image run"))
    def select_as_active_image_run(self, request, queryset):
        for run in queryset.select_related("asset_job"):
            run.asset_job.selected_image_run = run
            run.asset_job.save(update_fields=["selected_image_run", "updated_at"])
        self.message_user(request, _("Selected run(s) set as active."))


@admin.register(VideoClipGenerationRun)
class VideoClipGenerationRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "run_number",
        "run_status_badge",
        "provider",
        "clips_count",
        "total_cost_usd",
        "completed_at",
    ]
    list_filter = ["status", "provider", "created_at"]
    search_fields = ["asset_job__id", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "celery_task_id"]
    ordering = ["asset_job", "run_number"]
    inlines = [GeneratedVideoClipInline]
    actions = ["select_as_active_clip_run"]

    @display(description=_("Status"), ordering="status", label=_RUN_STATUS_LABELS)
    def run_status_badge(self, obj: VideoClipGenerationRun) -> str:
        return obj.status

    @admin.action(description=_("Select as active video clip run"))
    def select_as_active_clip_run(self, request, queryset):
        for run in queryset.select_related("asset_job"):
            run.asset_job.selected_video_clip_run = run
            run.asset_job.save(update_fields=["selected_video_clip_run", "updated_at"])
        self.message_user(request, _("Selected run(s) set as active."))


@admin.register(ThumbnailRun)
class ThumbnailRunAdmin(ModelAdmin):
    list_display = [
        "id",
        "asset_job",
        "run_number",
        "run_status_badge",
        "provider",
        "options_count",
        "total_cost_usd",
        "completed_at",
    ]
    list_filter = ["status", "provider", "created_at"]
    search_fields = ["asset_job__id", "asset_job__script_job__final_title"]
    readonly_fields = ["id", "created_at", "updated_at", "celery_task_id"]
    ordering = ["asset_job", "run_number"]
    inlines = [ThumbnailOptionInline]
    actions = ["select_as_active_thumbnail_run"]

    @display(description=_("Status"), ordering="status", label=_RUN_STATUS_LABELS)
    def run_status_badge(self, obj: ThumbnailRun) -> str:
        return obj.status

    @admin.action(description=_("Select as active thumbnail run"))
    def select_as_active_thumbnail_run(self, request, queryset):
        for run in queryset.select_related("asset_job"):
            run.asset_job.selected_thumbnail_run = run
            run.asset_job.save(update_fields=["selected_thumbnail_run", "updated_at"])
        self.message_user(request, _("Selected run(s) set as active."))


# ── Legacy child-model Admin Classes (kept for direct access) ─────────────────


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
