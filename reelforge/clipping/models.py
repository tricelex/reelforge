from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.***REMOVED***.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django_fsm import FSMField
from django_fsm import transition

from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.clipping.constants import CaptionAnimation
from ***REMOVED***.clipping.constants import CaptionPosition
from ***REMOVED***.clipping.constants import CaptionStyle
from ***REMOVED***.clipping.constants import HookStyle
from ***REMOVED***.clipping.constants import MediaAssetType
from ***REMOVED***.clipping.constants import ProgressBarPosition
from ***REMOVED***.clipping.constants import RenderMode as ClipRenderMode
from ***REMOVED***.clipping.constants import TransitionStyle
from ***REMOVED***.clipping.constants import WatermarkPosition
from ***REMOVED***.clipping.constants import WatermarkType
from ***REMOVED***.core.models import BaseAbstractModel

if TYPE_CHECKING:
    from collections.abc import Iterable


class ClippingJob(BaseAbstractModel):
    class Status(models.TextChoices):
        INITIALIZING = "INITIALIZING", "Initializing"
        DOWNLOADING = "DOWNLOADING", "Downloading"
        TRANSCRIBING = "TRANSCRIBING", "Transcribing"
        ANALYZING = "ANALYZING", "Analyzing"
        AWAITING_CLIP_APPROVAL = "AWAITING_CLIP_APPROVAL", "Awaiting Clip Approval"
        RENDERING = "RENDERING", "Rendering"
        DISTRIBUTING = "DISTRIBUTING", "Distributing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        PAUSED = "PAUSED", "Paused"

    class SourceType(models.TextChoices):
        YOUTUBE_URL = "YOUTUBE_URL", "YouTube URL"
        DIRECT_URL = "DIRECT_URL", "Direct URL"
        UPLOAD = "UPLOAD", "File Upload"

    social_account = models.ForeignKey(
        SocialAccount,
        on_delete=models.PROTECT,
        related_name="clipping_jobs",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.YOUTUBE_URL,
    )
    source_url = models.URLField(blank=True)
    source_video_file = models.FileField(
        upload_to="clipping/source/",
        blank=True,
        null=True,
        max_length=500,
    )
    downloaded_file = models.FileField(
        upload_to="clipping/downloaded/",
        blank=True,
        null=True,
        max_length=500,
    )
    source_title = models.CharField(max_length=500, blank=True)
    source_duration_sec = models.FloatField(null=True, blank=True)

    # Transcription
    transcript_text = models.TextField(blank=True)
    transcript_json = models.JSONField(default=dict, blank=True)
    transcription_provider = models.CharField(max_length=50, blank=True)
    transcription_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal(0),
    )

    # Analysis
    clips_requested = models.PositiveIntegerField(default=5)
    analysis_provider = models.CharField(max_length=50, blank=True)
    analysis_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal(0),
    )

    # Agent
    agent_run_id = models.CharField(max_length=255, blank=True)
    agent_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal(0),
    )

    # Analysis Manifest — structured output from analysis task
    analysis_manifest = models.JSONField(null=True, blank=True)

    # Derived display assets
    thumbnail_strip_file = models.FileField(
        upload_to="clipping/thumbnails/",
        blank=True,
        null=True,
        max_length=500,
    )
    waveform_data_file = models.FileField(
        upload_to="clipping/waveforms/",
        blank=True,
        null=True,
        max_length=500,
    )

    # Task tracking
    celery_task_id = models.CharField(max_length=255, blank=True)

    # FSM
    status = FSMField(
        default=Status.INITIALIZING,
        protected=True,
        choices=Status.choices,
    )

    # Timeline
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clipping Job"
        verbose_name_plural = "Clipping Jobs"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["social_account"]),
        ]

    def __str__(self) -> str:
        return f"Clip: {self.source_title[:60] or self.source_url[:60]}"

    def refresh_from_db(
        self,
        using: str | None = None,
        fields: Iterable[str] | None = None,
        from_queryset: models.QuerySet | None = None,
    ) -> None:
        """Override to allow refresh_from_db() to work with protected FSMField.

        django_fsm FSMField(protected=True) blocks setattr() once the field is in
        __dict__. refresh_from_db() calls setattr() internally, which raises
        AttributeError. We temporarily remove the status key from __dict__ so the
        FSM descriptor's protection check is bypassed during the refresh.
        """
        fsm_field_names = [f.name for f in self._meta.concrete_fields if isinstance(f, FSMField)]
        for name in fsm_field_names:
            self.__dict__.pop(name, None)
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)

    @property
    def total_cost_usd(self) -> Decimal:
        return (self.transcription_cost_usd or Decimal(0)) + (self.analysis_cost_usd or Decimal(0))

    @property
    def platform(self) -> str:
        return self.social_account.platform

    # --- FSM transitions ---

    @transition(field=status, source=Status.INITIALIZING, target=Status.DOWNLOADING)
    def begin_download(self) -> None:
        self.started_at = timezone.now()

    @transition(field=status, source=Status.DOWNLOADING, target=Status.TRANSCRIBING)
    def begin_transcription(self) -> None:
        pass

    @transition(field=status, source=Status.TRANSCRIBING, target=Status.ANALYZING)
    def begin_analysis(self) -> None:
        pass

    @transition(field=status, source=Status.ANALYZING, target=Status.AWAITING_CLIP_APPROVAL)
    def await_clip_approval(self) -> None:
        pass

    @transition(
        field=status,
        source=[Status.ANALYZING, Status.AWAITING_CLIP_APPROVAL],
        target=Status.RENDERING,
    )
    def begin_rendering(self) -> None:
        pass

    @transition(field=status, source=Status.RENDERING, target=Status.DISTRIBUTING)
    def begin_distribution(self) -> None:
        pass

    @transition(field=status, source=Status.DISTRIBUTING, target=Status.COMPLETED)
    def mark_completed(self) -> None:
        self.completed_at = timezone.now()

    @transition(field=status, source="*", target=Status.FAILED)
    def mark_failed(self, error: str = "", trace: str = "") -> None:
        self.last_error = error
        self.failed_at = timezone.now()

    @transition(
        field=status,
        source=[
            Status.DOWNLOADING,
            Status.TRANSCRIBING,
            Status.ANALYZING,
            Status.AWAITING_CLIP_APPROVAL,
            Status.RENDERING,
            Status.DISTRIBUTING,
        ],
        target=Status.PAUSED,
    )
    def pause(self) -> None:
        pass

    @transition(field=status, source=Status.PAUSED, target=Status.AWAITING_CLIP_APPROVAL)
    def resume_to_approval(self) -> None:
        pass

    @transition(field=status, source=Status.PAUSED, target=Status.RENDERING)
    def resume_to_rendering(self) -> None:
        pass

    @transition(
        field=status,
        source=[Status.FAILED, Status.TRANSCRIBING],
        target=Status.TRANSCRIBING,
    )
    def retry_transcription(self) -> None:
        self.last_error = ""

    @transition(
        field=status,
        source=[Status.FAILED, Status.ANALYZING],
        target=Status.ANALYZING,
    )
    def retry_analysis(self) -> None:
        self.last_error = ""


class ClipCandidate(BaseAbstractModel):
    class CandidateStatus(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        RENDERING = "RENDERING", "Rendering"
        RENDERED = "RENDERED", "Rendered"
        DISTRIBUTING = "DISTRIBUTING", "Distributing"
        DISTRIBUTED = "DISTRIBUTED", "Distributed"

    clipping_job = models.ForeignKey(
        ClippingJob,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    title = models.CharField(max_length=200)
    hook_text = models.CharField(max_length=200, blank=True)
    caption_template = models.TextField(blank=True)
    relevance_score = models.FloatField(default=0.0)
    reason = models.TextField(blank=True)
    transcript_excerpt = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=CandidateStatus.choices,
        default=CandidateStatus.PROPOSED,
    )
    approved = models.BooleanField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_clip_candidates",
    )
    rejection_reason = models.TextField(blank=True)
    # Review gates — stage order numbers at which the render should pause for operator review.
    # e.g. [1, 3, 5, 8]. Empty list = no gates.
    render_gates = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-relevance_score"]
        verbose_name = "Clip Candidate"
        verbose_name_plural = "Clip Candidates"

    def __str__(self) -> str:
        return f"{self.title[:50]} ({self.start_sec:.0f}s\u2013{self.end_sec:.0f}s)"

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def clean(self) -> None:
        super().clean()
        if self.end_sec <= self.start_sec:
            raise ValidationError("end_sec must be greater than start_sec")
        duration = self.end_sec - self.start_sec
        if duration < 30:
            raise ValidationError(
                f"Clip duration {duration:.1f}s is below minimum 30s"
            )
        if duration > 180:
            raise ValidationError(
                f"Clip duration {duration:.1f}s exceeds maximum 180s"
            )
        # Overlap detection (±1s tolerance for frame precision)
        # Use pk=0 fallback so .exclude() works correctly for unsaved records (pk=None)
        overlapping = ClipCandidate.objects.filter(
            clipping_job=self.clipping_job,
            start_sec__lt=self.end_sec + 1,
            end_sec__gt=self.start_sec - 1,
        ).exclude(pk=self.pk or 0)
        if overlapping.exists():
            other = overlapping.first()
            raise ValidationError(
                f"Clip overlaps with existing candidate '{other.title}' "
                f"({other.start_sec:.0f}s\u2013{other.end_sec:.0f}s)"
            )


class ClipRender(BaseAbstractModel):
    class Format(models.TextChoices):
        VERTICAL_9_16 = "VERTICAL_9_16", "Vertical 9:16"
        LANDSCAPE_16_9 = "LANDSCAPE_16_9", "Landscape 16:9"
        SQUARE_1_1 = "SQUARE_1_1", "Square 1:1"

    class RenderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        PAUSED_AT_GATE = "PAUSED_AT_GATE", "Paused at Gate"

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="renders",
    )
    format = models.CharField(
        max_length=20,
        choices=Format.choices,
        default=Format.VERTICAL_9_16,
    )
    video_file = models.FileField(
        upload_to="clipping/renders/",
        blank=True,
        null=True,
        max_length=500,
    )
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    include_captions = models.BooleanField(default=True)
    include_title_card = models.BooleanField(default=True)
    include_branding = models.BooleanField(default=True)
    render_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=RenderStatus.choices,
        default=RenderStatus.PENDING,
    )
    celery_task_id = models.CharField(max_length=255, blank=True)
    render_duration_sec = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    paused_at_stage = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clip Render"
        verbose_name_plural = "Clip Renders"

    def __str__(self) -> str:
        return f"Render {self.format} \u2014 {self.candidate}"


class ClipPost(BaseAbstractModel):
    class PostStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        POSTING = "POSTING", "Posting"
        POSTED = "POSTED", "Posted"
        SCHEDULED = "SCHEDULED", "Scheduled"
        FAILED = "FAILED", "Failed"

    render = models.ForeignKey(
        ClipRender,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    social_account = models.ForeignKey(
        SocialAccount,
        on_delete=models.CASCADE,
        related_name="clip_posts",
    )
    caption = models.TextField(blank=True)
    title = models.CharField(max_length=200, blank=True)
    hashtags = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PostStatus.choices,
        default=PostStatus.PENDING,
    )
    platform_post_id = models.CharField(max_length=255, blank=True)
    platform_url = models.URLField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)

    # Performance metrics
    views = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal(0),
    )
    last_analytics_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Clip Post"
        verbose_name_plural = "Clip Posts"

    def __str__(self) -> str:
        return f"{self.social_account.get_platform_display()} post \u2014 {self.render}"


class ClipLayoutConfig(BaseAbstractModel):
    """Stores render mode and layout parameters for a ClipCandidate.

    Auto-created by a post_save signal on ClipCandidate, pre-populated from
    the channel's default_render_mode and default_layout_config.
    """

    # Expose RenderMode as a class attribute for external access (tasks, admin, etc.)
    RenderMode = ClipRenderMode

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="layout_config",
    )
    render_mode = models.CharField(
        max_length=20,
        choices=ClipRenderMode.choices,
        default=ClipRenderMode.SMART_CROP,
    )
    render_format = models.CharField(
        max_length=20,
        choices=ClipRender.Format.choices,
        default=ClipRender.Format.VERTICAL_9_16,
    )

    # Smart Crop manual override — all null means auto-detect via face detection
    manual_crop_x = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_y = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_w = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_h = models.PositiveIntegerField(null=True, blank=True)

    # Spatial Stack — Region A (top slot)
    region_a_label = models.CharField(max_length=100, blank=True, default="Region A")
    region_a_x = models.PositiveIntegerField(null=True, blank=True)
    region_a_y = models.PositiveIntegerField(null=True, blank=True)
    region_a_w = models.PositiveIntegerField(null=True, blank=True)
    region_a_h = models.PositiveIntegerField(null=True, blank=True)

    # Spatial Stack — Region B (bottom slot)
    region_b_label = models.CharField(max_length=100, blank=True, default="Region B")
    region_b_x = models.PositiveIntegerField(null=True, blank=True)
    region_b_y = models.PositiveIntegerField(null=True, blank=True)
    region_b_w = models.PositiveIntegerField(null=True, blank=True)
    region_b_h = models.PositiveIntegerField(null=True, blank=True)
    # Fraction of output height given to region A (top). Region B gets 1 - stack_ratio.
    stack_ratio = models.FloatField(default=0.6)

    # Detection quality — written back by render_clip task after SMART_CROP render
    face_detected = models.BooleanField(null=True, blank=True)
    detection_confidence = models.FloatField(null=True, blank=True)

    # Preview image — written by preview_clip_layout task
    preview_image = models.ImageField(
        upload_to="clipping/previews/",
        null=True,
        blank=True,
        max_length=500,
    )

    class Meta:
        verbose_name = "Clip Layout Config"
        verbose_name_plural = "Clip Layout Configs"

    def __str__(self) -> str:
        return f"{self.get_render_mode_display()} — {self.candidate}"

    @property
    def has_manual_smart_crop(self) -> bool:
        """True only when all four manual crop fields are set."""
        return all(
            v is not None
            for v in [
                self.manual_crop_x,
                self.manual_crop_y,
                self.manual_crop_w,
                self.manual_crop_h,
            ]
        )

    @property
    def has_spatial_regions(self) -> bool:
        """True only when all eight region A + B coordinate fields are set."""
        return all(
            v is not None
            for v in [
                self.region_a_x,
                self.region_a_y,
                self.region_a_w,
                self.region_a_h,
                self.region_b_x,
                self.region_b_y,
                self.region_b_w,
                self.region_b_h,
            ]
        )


# ---------------------------------------------------------------------------
# Style mixin — shared by ClipRenderTemplate (channel) and ClipStyleConfig (clip)
# ---------------------------------------------------------------------------


class ClipRenderStyleMixin(models.Model):
    """Abstract mixin providing all render style fields.

    Both ClipRenderTemplate (channel-level) and ClipStyleConfig (per-clip)
    inherit this so the operator can override any field at the clip level.
    """

    # Caption
    caption_enabled = models.BooleanField(default=True)
    caption_style = models.CharField(
        max_length=20, choices=CaptionStyle.choices, default=CaptionStyle.CHUNKED
    )
    caption_font = models.CharField(max_length=100, default="Montserrat-Bold")
    caption_size = models.PositiveIntegerField(default=52)
    caption_color = models.CharField(max_length=9, default="#FFFFFF")
    caption_stroke_color = models.CharField(max_length=9, default="#000000")
    caption_stroke_width = models.PositiveIntegerField(default=3)
    caption_bg_color = models.CharField(max_length=9, blank=True, default="")
    caption_position = models.CharField(
        max_length=10, choices=CaptionPosition.choices, default=CaptionPosition.BOTTOM
    )
    caption_animation = models.CharField(
        max_length=10, choices=CaptionAnimation.choices, default=CaptionAnimation.POP
    )
    caption_language = models.CharField(max_length=10, default="en")
    caption_translate_to = models.CharField(max_length=10, blank=True, default="")
    emoji_keyword_map = models.JSONField(default=dict, blank=True)

    # Hook
    hook_enabled = models.BooleanField(default=True)
    hook_style = models.CharField(
        max_length=20, choices=HookStyle.choices, default=HookStyle.OVERLAY_TOP
    )
    hook_duration_sec = models.FloatField(default=2.5)
    hook_font = models.CharField(max_length=100, default="Montserrat-Bold")
    hook_size = models.PositiveIntegerField(default=60)
    hook_color = models.CharField(max_length=9, default="#FFFFFF")
    hook_bg_color = models.CharField(max_length=9, default="#CC000000")
    hook_animation = models.CharField(
        max_length=10, choices=CaptionAnimation.choices, default=CaptionAnimation.FADE
    )

    # Transitions
    intro_transition = models.CharField(
        max_length=20, choices=TransitionStyle.choices, default=TransitionStyle.NONE
    )
    outro_transition = models.CharField(
        max_length=20, choices=TransitionStyle.choices, default=TransitionStyle.NONE
    )
    transition_duration_sec = models.FloatField(default=0.5)

    # Watermark
    watermark_enabled = models.BooleanField(default=False)
    watermark_type = models.CharField(
        max_length=10, choices=WatermarkType.choices, default=WatermarkType.TEXT
    )
    watermark_text = models.CharField(max_length=100, blank=True, default="")
    watermark_image = models.ImageField(
        upload_to="clipping/watermarks/", blank=True, null=True
    )
    watermark_position = models.CharField(
        max_length=15,
        choices=WatermarkPosition.choices,
        default=WatermarkPosition.BOTTOM_RIGHT,
    )
    watermark_opacity = models.FloatField(default=0.6)
    watermark_size = models.PositiveIntegerField(default=32)

    # Progress bar
    progress_bar_enabled = models.BooleanField(default=False)
    progress_bar_position = models.CharField(
        max_length=10,
        choices=ProgressBarPosition.choices,
        default=ProgressBarPosition.TOP,
    )
    progress_bar_color = models.CharField(max_length=9, default="#FFFFFF")
    progress_bar_height = models.PositiveIntegerField(default=6)

    # Background music
    music_enabled = models.BooleanField(default=False)
    music_volume_db = models.FloatField(default=-20.0)
    music_fade_in_sec = models.FloatField(default=1.0)
    music_fade_out_sec = models.FloatField(default=1.0)

    STYLE_FIELD_NAMES: list[str] = [
        "caption_enabled", "caption_style", "caption_font", "caption_size",
        "caption_color", "caption_stroke_color", "caption_stroke_width",
        "caption_bg_color", "caption_position", "caption_animation",
        "caption_language", "caption_translate_to", "emoji_keyword_map",
        "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
        "hook_size", "hook_color", "hook_bg_color", "hook_animation",
        "intro_transition", "outro_transition", "transition_duration_sec",
        "watermark_enabled", "watermark_type", "watermark_text", "watermark_image",
        "watermark_position", "watermark_opacity", "watermark_size",
        "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
        "progress_bar_height",
        "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
    ]

    class Meta:
        abstract = True


class ClipRenderTemplate(ClipRenderStyleMixin, BaseAbstractModel):
    """Global render style defaults. One can be marked as the system default."""

    name = models.CharField(max_length=100, default="Default Template")
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Clip Render Template"
        verbose_name_plural = "Clip Render Templates"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="unique_default_render_template",
            )
        ]

    def __str__(self) -> str:
        return f"{'[Default] ' if self.is_default else ''}{self.name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.is_default:
            ClipRenderTemplate.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def to_style_defaults(self) -> dict[str, Any]:
        """Return all style fields suitable for seeding a ClipStyleConfig."""
        result: dict[str, Any] = {}
        for name in self.STYLE_FIELD_NAMES:
            value = getattr(self, name)
            if hasattr(value, "name"):
                value = value.name or ""
            result[name] = value
        return result


class ClipMediaAsset(BaseAbstractModel):
    """Intro or outro video clip library.

    Operator uploads short branded clips; duration_sec is auto-detected via ffprobe.
    """

    asset_type = models.CharField(
        max_length=10, choices=MediaAssetType.choices, default=MediaAssetType.INTRO
    )
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="clipping/media_assets/", max_length=500, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    thumbnail = models.ImageField(
        upload_to="clipping/media_assets/thumbs/",
        blank=True,
        null=True,
        max_length=500,
    )

    class Meta:
        ordering = ["asset_type", "name"]
        verbose_name = "Clip Media Asset"
        verbose_name_plural = "Clip Media Assets"
        indexes = [
            models.Index(fields=["asset_type", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_asset_type_display()} — {self.name}"


class ClipMusicAsset(BaseAbstractModel):
    """Background music track library."""

    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="clipping/music_assets/", max_length=500, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    genre = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    waveform_file = models.FileField(
        upload_to="clipping/music_assets/waveforms/",
        blank=True,
        null=True,
        max_length=500,
    )

    class Meta:
        ordering = ["genre", "name"]
        verbose_name = "Clip Music Asset"
        verbose_name_plural = "Clip Music Assets"
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.genre or 'no genre'})"


class ClipStyleConfig(ClipRenderStyleMixin, BaseAbstractModel):
    """Per-clip render style overrides. Auto-created on ClipCandidate save,
    pre-populated from the channel's ClipRenderTemplate.
    """

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="style_config",
    )
    render_template = models.ForeignKey(
        ClipRenderTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seeded_style_configs",
    )
    intro_asset = models.ForeignKey(
        ClipMediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intro_style_configs",
        limit_choices_to={"asset_type": MediaAssetType.INTRO},
    )
    outro_asset = models.ForeignKey(
        ClipMediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outro_style_configs",
        limit_choices_to={"asset_type": MediaAssetType.OUTRO},
    )
    music_asset = models.ForeignKey(
        ClipMusicAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="style_configs",
    )
    translated_transcript_json = models.JSONField(default=dict, blank=True)
    preview_image = models.ImageField(
        upload_to="clipping/style_previews/",
        null=True,
        blank=True,
        max_length=500,
    )

    class Meta:
        verbose_name = "Clip Style Config"
        verbose_name_plural = "Clip Style Configs"

    def __str__(self) -> str:
        return f"Style: {self.candidate}"


class ClipTimedOverlay(BaseAbstractModel):
    """A time-ranged text or image overlay applied in the final output.

    Timestamps reference final output time (including intro + hook prepend).
    """

    class OverlayType(models.TextChoices):
        TEXT = "TEXT", "Text"
        IMAGE = "IMAGE", "Image"

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="timed_overlays",
    )
    overlay_type = models.CharField(
        max_length=10, choices=OverlayType.choices, default=OverlayType.TEXT
    )
    text = models.CharField(max_length=300, blank=True)
    image = models.ImageField(
        upload_to="clipping/timed_overlays/", null=True, blank=True, max_length=500
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    position_x = models.PositiveIntegerField(default=540)
    position_y = models.PositiveIntegerField(default=960)
    opacity = models.FloatField(default=1.0)
    font_size = models.PositiveIntegerField(default=40)
    font_color = models.CharField(max_length=9, default="#FFFFFF")

    class Meta:
        ordering = ["start_sec"]
        verbose_name = "Timed Overlay"
        verbose_name_plural = "Timed Overlays"

    def __str__(self) -> str:
        return f"Overlay [{self.start_sec:.1f}s\u2013{self.end_sec:.1f}s] on {self.candidate}"

    def clean(self) -> None:
        super().clean()
        if self.end_sec <= self.start_sec:
            raise ValidationError("end_sec must be greater than start_sec")


class ClipRenderStageResult(BaseAbstractModel):
    """Per-stage tracking record for a ClipRender pipeline run.

    One record per stage per render. Created by the pipeline before each stage,
    updated on completion or failure. Enables per-stage inspection and retry.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    render = models.ForeignKey(
        ClipRender,
        on_delete=models.CASCADE,
        related_name="stage_results",
    )
    stage_name = models.CharField(max_length=100)
    stage_order = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    output_file = models.FileField(
        upload_to="clipping/stage_outputs/",
        null=True,
        blank=True,
        max_length=500,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["stage_order"]
        verbose_name = "Render Stage Result"
        verbose_name_plural = "Render Stage Results"
        unique_together = [("render", "stage_order")]

    def __str__(self) -> str:
        return f"Stage {self.stage_order} ({self.stage_name}) \u2014 {self.render_id}"
