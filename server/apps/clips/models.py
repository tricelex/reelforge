"""ORM models for the clips app."""

from decimal import Decimal
from typing import ClassVar, override

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionAnimation,
    CaptionPosition,
    CaptionStyle,
    HookStyle,
    OverlayType,
    PostStatus,
    ProgressBarPosition,
    RenderFormat,
    RenderMode,
    TransitionStyle,
    WatermarkPosition,
    WatermarkType,
)
from server.common.models import TimeStampedModel, UUIDModel


class ClipCandidate(UUIDModel, TimeStampedModel):
    """AI-identified or manually-created clip segment within a pipeline run."""

    run = models.ForeignKey(
        'pipelines.PipelineRun',
        on_delete=models.CASCADE,
        related_name='clip_candidates',
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
    rejection_reason = models.TextField(blank=True)
    render_asset_id = models.UUIDField(null=True, blank=True)
    is_manual = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar = ['-relevance_score']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipcandidate_status_valid',
                condition=models.Q(status__in=CandidateStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return (
            f'{self.title[:50]}'
            f' ({self.start_sec:.0f}s-{self.end_sec:.0f}s)'
        )

    @property
    def duration_sec(self) -> float:
        """Return clip duration in seconds."""
        return self.end_sec - self.start_sec


class ClipLayoutConfig(UUIDModel, TimeStampedModel):
    """Crop/layout config for one ClipCandidate. Auto-created by signal."""

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='layout_config',
    )
    render_mode = models.CharField(
        max_length=20,
        choices=RenderMode.choices,
        default=RenderMode.SMART_CROP,
    )
    render_format = models.CharField(
        max_length=20,
        choices=RenderFormat.choices,
        default=RenderFormat.VERTICAL_9_16,
    )
    manual_crop_x = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_y = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_w = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_h = models.PositiveIntegerField(null=True, blank=True)
    region_a_x = models.PositiveIntegerField(null=True, blank=True)
    region_a_y = models.PositiveIntegerField(null=True, blank=True)
    region_a_w = models.PositiveIntegerField(null=True, blank=True)
    region_a_h = models.PositiveIntegerField(null=True, blank=True)
    region_b_x = models.PositiveIntegerField(null=True, blank=True)
    region_b_y = models.PositiveIntegerField(null=True, blank=True)
    region_b_w = models.PositiveIntegerField(null=True, blank=True)
    region_b_h = models.PositiveIntegerField(null=True, blank=True)
    stack_ratio = models.FloatField(default=0.6)
    face_detected = models.BooleanField(null=True, blank=True)
    detection_confidence = models.FloatField(null=True, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_cliplayoutconfig_render_mode_valid',
                condition=models.Q(render_mode__in=RenderMode.values),
            ),
            models.CheckConstraint(
                name='clips_cliplayoutconfig_render_format_valid',
                condition=models.Q(render_format__in=RenderFormat.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.render_mode} — {self.candidate}'

    @property
    def has_manual_smart_crop(self) -> bool:
        """Return True if all manual smart crop coordinates are set."""
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
        """Return True if all spatial stack region coordinates are set."""
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


class ClipStyleConfig(UUIDModel, TimeStampedModel):
    """Visual style config for one ClipCandidate. Auto-created by signal."""

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='style_config',
    )
    caption_enabled = models.BooleanField(default=True)
    caption_style = models.CharField(
        max_length=20,
        choices=CaptionStyle.choices,
        default=CaptionStyle.CHUNKED,
    )
    caption_font = models.CharField(max_length=100, default='Montserrat-Bold')
    caption_size = models.PositiveIntegerField(default=52)
    caption_color = models.CharField(max_length=9, default='#FFFFFF')
    caption_stroke_color = models.CharField(max_length=9, default='#000000')
    caption_stroke_width = models.PositiveIntegerField(default=3)
    caption_bg_color = models.CharField(max_length=9, blank=True, default='')
    caption_position = models.CharField(
        max_length=10,
        choices=CaptionPosition.choices,
        default=CaptionPosition.BOTTOM,
    )
    caption_animation = models.CharField(
        max_length=10,
        choices=CaptionAnimation.choices,
        default=CaptionAnimation.POP,
    )
    caption_language = models.CharField(max_length=10, default='en')
    caption_translate_to = models.CharField(
        max_length=10, blank=True, default='',
    )
    emoji_keyword_map = models.JSONField(default=dict, blank=True)
    hook_enabled = models.BooleanField(default=True)
    hook_style = models.CharField(
        max_length=20,
        choices=HookStyle.choices,
        default=HookStyle.OVERLAY_TOP,
    )
    hook_duration_sec = models.FloatField(default=2.5)
    hook_font = models.CharField(max_length=100, default='Montserrat-Bold')
    hook_size = models.PositiveIntegerField(default=60)
    hook_color = models.CharField(max_length=9, default='#FFFFFF')
    hook_bg_color = models.CharField(max_length=9, default='#CC000000')
    intro_transition = models.CharField(
        max_length=20,
        choices=TransitionStyle.choices,
        default=TransitionStyle.NONE,
    )
    outro_transition = models.CharField(
        max_length=20,
        choices=TransitionStyle.choices,
        default=TransitionStyle.NONE,
    )
    watermark_enabled = models.BooleanField(default=False)
    watermark_type = models.CharField(
        max_length=10,
        choices=WatermarkType.choices,
        default=WatermarkType.TEXT,
    )
    watermark_text = models.CharField(max_length=100, blank=True, default='')
    watermark_image = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    watermark_position = models.CharField(
        max_length=15,
        choices=WatermarkPosition.choices,
        default=WatermarkPosition.BOTTOM_RIGHT,
    )
    watermark_opacity = models.FloatField(default=0.6)
    watermark_size = models.PositiveIntegerField(default=32)
    progress_bar_enabled = models.BooleanField(default=False)
    progress_bar_position = models.CharField(
        max_length=10,
        choices=ProgressBarPosition.choices,
        default=ProgressBarPosition.TOP,
    )
    progress_bar_color = models.CharField(max_length=9, default='#FFFFFF')
    progress_bar_height = models.PositiveIntegerField(default=6)
    intro_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    outro_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    music_enabled = models.BooleanField(default=False)
    music_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    music_volume_db = models.FloatField(default=-20.0)
    music_fade_in_sec = models.FloatField(default=1.0)
    music_fade_out_sec = models.FloatField(default=1.0)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipstyleconfig_caption_style_valid',
                condition=models.Q(caption_style__in=CaptionStyle.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_caption_position_valid',
                condition=models.Q(caption_position__in=CaptionPosition.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_caption_animation_valid',
                condition=models.Q(
                    caption_animation__in=CaptionAnimation.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_hook_style_valid',
                condition=models.Q(hook_style__in=HookStyle.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_intro_transition_valid',
                condition=models.Q(
                    intro_transition__in=TransitionStyle.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_outro_transition_valid',
                condition=models.Q(
                    outro_transition__in=TransitionStyle.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_watermark_type_valid',
                condition=models.Q(watermark_type__in=WatermarkType.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_watermark_position_valid',
                condition=models.Q(
                    watermark_position__in=WatermarkPosition.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_progress_bar_position_valid',
                condition=models.Q(
                    progress_bar_position__in=ProgressBarPosition.values,
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'Style — {self.candidate}'


class ClipTimedOverlay(UUIDModel, TimeStampedModel):
    """A text or image overlay active during a time range on a clip."""

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='timed_overlays',
    )
    overlay_type = models.CharField(
        max_length=10,
        choices=OverlayType.choices,
        default=OverlayType.TEXT,
    )
    text = models.CharField(max_length=500, blank=True)
    image_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    font_size = models.PositiveIntegerField(default=40)
    color = models.CharField(max_length=9, default='#FFFFFF')
    opacity = models.FloatField(default=1.0)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_cliptimedoverlay_overlay_type_valid',
                condition=models.Q(overlay_type__in=OverlayType.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return (
            f'Overlay "{self.text[:30]}"'
            f' ({self.start_sec:.1f}s-{self.end_sec:.1f}s)'
        )


class ClipPost(UUIDModel, TimeStampedModel):
    """A scheduled or completed post of a rendered clip to a social platform."""

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='posts',
    )
    platform = models.CharField(max_length=30)
    caption = models.TextField(blank=True)
    title = models.CharField(max_length=200, blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PostStatus.choices,
        default=PostStatus.PENDING,
    )
    platform_post_id = models.CharField(max_length=255, blank=True)
    platform_url = models.URLField(blank=True)
    last_error = models.TextField(blank=True)
    views = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal(0),
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clippost_status_valid',
                condition=models.Q(status__in=PostStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.platform} post — {self.candidate}'


@receiver(post_save, sender=ClipCandidate)
def create_clip_configs(
    sender: type[ClipCandidate],
    instance: ClipCandidate,
    created: bool,  # noqa: FBT001
    **kwargs: object,
) -> None:
    """Auto-create layout and style configs when a candidate is created."""
    if created:
        ClipLayoutConfig.objects.get_or_create(candidate=instance)
        ClipStyleConfig.objects.get_or_create(candidate=instance)
