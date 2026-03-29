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
from unfold.admin import StackedInline
from unfold.admin import TabularInline
from unfold.decorators import display

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay

logger = logging.getLogger("***REMOVED***.clipping")


class ClipLayoutConfigInline(StackedInline):
    model = ClipLayoutConfig
    extra = 0
    can_delete = False
    max_num = 1
    collapsible = True
    verbose_name = "Layout Config"
    verbose_name_plural = "Layout Config"
    readonly_fields = ("preview_thumbnail", "detection_summary")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("render_mode", "render_format"),
                    ("preview_thumbnail", "detection_summary"),
                ),
            },
        ),
        (
            "Smart Crop — Manual Override",
            {
                "fields": (
                    ("manual_crop_x", "manual_crop_y"),
                    ("manual_crop_w", "manual_crop_h"),
                ),
            },
        ),
        (
            "Spatial Stack — Region A",
            {
                "fields": (
                    "region_a_label",
                    ("region_a_x", "region_a_y"),
                    ("region_a_w", "region_a_h"),
                ),
            },
        ),
        (
            "Spatial Stack — Region B",
            {
                "fields": (
                    "region_b_label",
                    ("region_b_x", "region_b_y"),
                    ("region_b_w", "region_b_h"),
                    "stack_ratio",
                ),
            },
        ),
    )

    @display(description="Preview")
    def preview_thumbnail(self, obj: ClipLayoutConfig) -> str:
        if not obj.preview_image:
            return "—"
        return format_html(
            '<img src="{}" style="max-width:320px;max-height:180px;border-radius:4px;" />',
            obj.preview_image.url,
        )

    @display(description="Detection")
    def detection_summary(self, obj: ClipLayoutConfig) -> str:
        if obj.face_detected is None:
            return "—"
        status = "Face detected" if obj.face_detected else "No face (center crop used)"
        conf = f" ({obj.detection_confidence:.0%})" if obj.detection_confidence is not None else ""
        return f"{status}{conf}"


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


class ClipStyleConfigInline(StackedInline):
    model = ClipStyleConfig
    extra = 0
    can_delete = False
    max_num = 1
    collapsible = True
    verbose_name = "Style Config"
    verbose_name_plural = "Style Config"
    readonly_fields = ("preview_thumbnail",)
    fieldsets = (
        (
            "Asset Selection",
            {
                "fields": ("intro_asset", "outro_asset", "music_asset"),
            },
        ),
        (
            "Captions",
            {
                "fields": (
                    ("caption_enabled", "caption_style", "caption_position"),
                    ("caption_font", "caption_size"),
                    ("caption_color", "caption_stroke_color", "caption_stroke_width"),
                    "caption_bg_color",
                    ("caption_animation", "caption_language", "caption_translate_to"),
                    "emoji_keyword_map",
                ),
            },
        ),
        (
            "Hook",
            {
                "fields": (
                    ("hook_enabled", "hook_style", "hook_duration_sec"),
                    ("hook_font", "hook_size"),
                    ("hook_color", "hook_bg_color", "hook_animation"),
                ),
            },
        ),
        (
            "Transitions",
            {
                "fields": (
                    ("intro_transition", "outro_transition", "transition_duration_sec"),
                ),
            },
        ),
        (
            "Watermark",
            {
                "fields": (
                    ("watermark_enabled", "watermark_type"),
                    ("watermark_text", "watermark_image"),
                    ("watermark_position", "watermark_opacity", "watermark_size"),
                ),
            },
        ),
        (
            "Progress Bar",
            {
                "fields": (
                    ("progress_bar_enabled", "progress_bar_position"),
                    ("progress_bar_color", "progress_bar_height"),
                ),
            },
        ),
        (
            "Background Music",
            {
                "fields": (
                    ("music_enabled", "music_volume_db"),
                    ("music_fade_in_sec", "music_fade_out_sec"),
                ),
            },
        ),
        (
            "Preview",
            {
                "fields": ("preview_thumbnail",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest):  # type: ignore[override]
        return super().get_queryset(request).select_related("intro_asset", "outro_asset", "music_asset")

    def formfield_for_foreignkey(self, db_field, request: HttpRequest, **kwargs):  # type: ignore[override]
        """Filter asset FK dropdowns to the candidate's channel."""
        if db_field.name in ("intro_asset", "outro_asset", "music_asset"):
            candidate_id = request.resolver_match.kwargs.get("object_id")
            if candidate_id:
                try:
                    candidate = ClipCandidate.objects.select_related("clipping_job__channel").get(pk=candidate_id)
                    channel = candidate.clipping_job.channel
                    if db_field.name == "intro_asset":
                        kwargs["queryset"] = ClipMediaAsset.objects.filter(channel=channel, asset_type="INTRO", is_active=True)
                    elif db_field.name == "outro_asset":
                        kwargs["queryset"] = ClipMediaAsset.objects.filter(channel=channel, asset_type="OUTRO", is_active=True)
                    elif db_field.name == "music_asset":
                        kwargs["queryset"] = ClipMusicAsset.objects.filter(channel=channel, is_active=True)
                except ClipCandidate.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @display(description="Style Preview")
    def preview_thumbnail(self, obj: ClipStyleConfig) -> str:
        if not obj.preview_image:
            return "\u2014"
        return format_html(
            '<img src="{}" style="max-width:200px;max-height:360px;border-radius:4px;" />',
            obj.preview_image.url,
        )


class ClipTimedOverlayInline(TabularInline):
    model = ClipTimedOverlay
    extra = 0
    fields = (
        "overlay_type",
        "text",
        "image",
        "start_sec",
        "end_sec",
        "position_x",
        "position_y",
        "opacity",
        "font_size",
        "font_color",
    )
    ordering = ["start_sec"]


class ClipRenderStageResultInline(TabularInline):
    model = ClipRenderStageResult
    extra = 0
    can_delete = False
    ordering = ["stage_order"]
    readonly_fields = (
        "stage_order",
        "stage_name",
        "status_badge",
        "duration_display",
        "started_at",
        "completed_at",
        "last_error",
        "stage_output_preview",
    )
    fields = (
        "stage_order",
        "stage_name",
        "status_badge",
        "duration_display",
        "started_at",
        "completed_at",
        "last_error",
        "stage_output_preview",
    )

    @display(
        description="Status",
        label={
            "PENDING": "default",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "SKIPPED": "warning",
        },
    )
    def status_badge(self, obj: ClipRenderStageResult) -> str:
        return obj.status

    @display(description="Duration")
    def duration_display(self, obj: ClipRenderStageResult) -> str:
        if obj.duration_sec is None:
            return "\u2014"
        return f"{obj.duration_sec:.2f}s"

    @display(description="Output")
    def stage_output_preview(self, obj: ClipRenderStageResult) -> str:
        if not obj.output_file:
            return "\u2014"
        url = obj.output_file.url
        return format_html('<a href="{}" download>Download</a>', url)


@admin.register(ClipRender)
class ClipRenderAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "candidate",
        "format",
        "status_badge",
        "render_duration_sec",
        "file_size_bytes",
        "created_at",
    )
    list_filter = ("status", "format")
    search_fields = ("candidate__title", "candidate__clipping_job__source_title")
    readonly_fields = (
        "id",
        "candidate",
        "format",
        "status",
        "video_preview",
        "file_size_bytes",
        "render_duration_sec",
        "last_error",
        "created_at",
        "updated_at",
    )
    inlines = [ClipRenderStageResultInline]

    @display(
        description="Status",
        ordering="status",
        label={
            "PENDING": "default",
            "RENDERING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def status_badge(self, obj: ClipRender) -> str:
        return obj.status

    @display(description="Video")
    def video_preview(self, obj: ClipRender) -> str:
        if not obj.video_file:
            return "\u2014"
        url = obj.video_file.url
        return format_html(
            '<video src="{}" controls style="max-width:320px;max-height:568px;"></video>'
            '<br><a href="{}" download>Download</a>',
            url,
            url,
        )

    @admin.action(description="Retry full render (from stage 1)")
    def retry_full_render(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        triggered = 0
        for render in queryset:
            render_clip.delay(str(render.candidate_id), clip_render_id=str(render.id), start_from_stage=1)
            triggered += 1
        self.message_user(request, f"Queued full re-render for {triggered} render(s).", messages.SUCCESS)

    @admin.action(description="Retry from stage 2 (skip trim/crop)")
    def retry_from_stage_2(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        triggered = 0
        for render in queryset:
            render_clip.delay(str(render.candidate_id), clip_render_id=str(render.id), start_from_stage=2)
            triggered += 1
        self.message_user(request, f"Queued re-render from stage 2 for {triggered} render(s).", messages.SUCCESS)

    @admin.action(description="Retry from captions (stage 4)")
    def retry_from_captions(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        triggered = 0
        for render in queryset:
            render_clip.delay(str(render.candidate_id), clip_render_id=str(render.id), start_from_stage=4)
            triggered += 1
        self.message_user(
            request,
            f"Queued re-render from captions (stage 4) for {triggered} render(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Clear stage outputs (reset to PENDING)")
    def clear_stage_outputs(self, request: HttpRequest, queryset) -> None:
        cleared = 0
        for render in queryset:
            deleted_count, _ = render.stage_results.all().delete()
            cleared += deleted_count
        self.message_user(
            request,
            f"Cleared {cleared} stage result(s) across {queryset.count()} render(s).",
            messages.SUCCESS,
        )

    actions = ["retry_full_render", "retry_from_stage_2", "retry_from_captions", "clear_stage_outputs"]


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
        from ***REMOVED***.clipping.tasks import download_source_video

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
        from ***REMOVED***.clipping.tasks import transcribe_video

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
        from ***REMOVED***.clipping.tasks import render_clip

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
        "render_mode_badge",
        "status",
        "approved",
        "updated_at",
    )
    list_filter = ("status", "approved", "layout_config__render_mode", "updated_at")
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
    inlines = [ClipLayoutConfigInline, ClipStyleConfigInline, ClipTimedOverlayInline, ClipRenderInline]

    @display(
        description="Layout",
        label={
            "SMART_CROP": "info",
            "SPATIAL_STACK": "warning",
            "CENTER_CROP": "default",
        },
    )
    def render_mode_badge(self, obj: ClipCandidate) -> str:
        try:
            return obj.layout_config.render_mode
        except ClipLayoutConfig.DoesNotExist:
            return "CENTER_CROP"

    @admin.action(description="Generate layout preview image")
    def generate_preview(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import preview_clip_layout

        queued = 0
        skipped = 0
        for candidate in queryset:
            try:
                lc = candidate.layout_config
                preview_clip_layout.delay(str(lc.id))
                queued += 1
            except ClipLayoutConfig.DoesNotExist:
                skipped += 1

        if queued:
            self.message_user(request, f"Queued preview generation for {queued} candidate(s).", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} candidate(s) — no layout config found.",
                messages.WARNING,
            )

    @admin.action(description="Generate style preview image")
    def generate_style_preview(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import preview_clip_style

        queued = 0
        skipped = 0
        for candidate in queryset:
            try:
                sc = candidate.style_config
                preview_clip_style.delay(str(sc.id))
                queued += 1
            except ClipStyleConfig.DoesNotExist:
                skipped += 1

        if queued:
            self.message_user(request, f"Queued style preview for {queued} candidate(s).", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Skipped {skipped} — no style config found.", messages.WARNING)

    actions = ["generate_preview", "generate_style_preview"]


@admin.register(ClipMediaAsset)
class ClipMediaAssetAdmin(ModelAdmin):
    list_display = ("name", "channel", "asset_type_badge", "duration_display", "is_active", "created_at")
    list_filter = ("asset_type", "is_active", "channel")
    search_fields = ("name", "channel__name")
    readonly_fields = ("id", "duration_sec", "created_at", "updated_at", "video_preview")

    @display(description="Type", label={"INTRO": "info", "OUTRO": "warning"})
    def asset_type_badge(self, obj: ClipMediaAsset) -> str:
        return obj.asset_type

    @display(description="Duration")
    def duration_display(self, obj: ClipMediaAsset) -> str:
        if obj.duration_sec is None:
            return "\u2014"
        return f"{obj.duration_sec:.1f}s"

    @display(description="Preview")
    def video_preview(self, obj: ClipMediaAsset) -> str:
        if not obj.file:
            return "\u2014"
        return format_html(
            '<video src="{}" controls style="max-width:240px;max-height:135px;"></video>',
            obj.file.url,
        )


@admin.register(ClipMusicAsset)
class ClipMusicAssetAdmin(ModelAdmin):
    list_display = ("name", "channel", "genre", "duration_display", "bpm", "is_active", "created_at")
    list_filter = ("is_active", "genre", "channel")
    search_fields = ("name", "channel__name", "genre")
    readonly_fields = ("id", "duration_sec", "created_at", "updated_at", "audio_preview")

    @display(description="Duration")
    def duration_display(self, obj: ClipMusicAsset) -> str:
        if obj.duration_sec is None:
            return "\u2014"
        return f"{obj.duration_sec:.1f}s"

    @display(description="Preview")
    def audio_preview(self, obj: ClipMusicAsset) -> str:
        if not obj.file:
            return "\u2014"
        return format_html('<audio src="{}" controls style="max-width:300px;"></audio>', obj.file.url)


__all__ = [
    "ClipCandidateAdmin",
    "ClipCandidateInline",
    "ClipLayoutConfigInline",
    "ClipMediaAssetAdmin",
    "ClipMusicAssetAdmin",
    "ClipPostAdmin",
    "ClipRenderAdmin",
    "ClipRenderInline",
    "ClipRenderStageResultInline",
    "ClipStyleConfigInline",
    "ClipTimedOverlayInline",
    "ClippingJobAdmin",
]
