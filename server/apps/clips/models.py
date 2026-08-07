"""ORM models for the clips app."""

from decimal import Decimal
from typing import ClassVar, override

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from server.apps.clips.logic.constants import (
    DEFAULT_BACKGROUND_COLOR,
    DEFAULT_BLUR_STRENGTH,
    BackgroundMode,
    CampaignStatus,
    CandidateStatus,
    CaptionAnimation,
    CaptionFont,
    CaptionPosition,
    CaptionStyle,
    ClipArrangement,
    ClipSourceStatus,
    ClipSourceType,
    ColorFilterPreset,
    FitMode,
    ForegroundTreatment,
    HookStyle,
    OverlayAnimation,
    OverlayShape,
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
    headline = models.CharField(max_length=200, blank=True)
    caption_template = models.TextField(blank=True)
    relevance_score = models.FloatField(default=0.0)
    hook_score = models.FloatField(default=0.0)
    flow_score = models.FloatField(default=0.0)
    value_score = models.FloatField(default=0.0)
    trend_score = models.FloatField(default=0.0)
    virality_score = models.FloatField(default=0.0)
    intent_match_score = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)
    score_version = models.CharField(max_length=16, blank=True, default='')
    hook_reason = models.TextField(blank=True)
    flow_reason = models.TextField(blank=True)
    value_reason = models.TextField(blank=True)
    trend_reason = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    transcript_excerpt = models.TextField(blank=True)
    #: Playback-ordered Hook/Story/Payoff beats (source in/out + notes).
    beats = models.JSONField(default=list, blank=True)
    arrangement = models.CharField(
        max_length=20,
        choices=ClipArrangement.choices,
        default=ClipArrangement.CONTIGUOUS,
    )
    status = models.CharField(
        max_length=20,
        choices=CandidateStatus.choices,
        default=CandidateStatus.PROPOSED,
    )
    rejection_reason = models.TextField(blank=True)
    render_asset_id = models.UUIDField(null=True, blank=True)
    preview_asset_id = models.UUIDField(null=True, blank=True)
    is_manual = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar = ['-virality_score', '-relevance_score']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipcandidate_status_valid',
                condition=models.Q(status__in=CandidateStatus.values),
            ),
            models.CheckConstraint(
                name='clips_clipcandidate_arrangement_valid',
                condition=models.Q(
                    arrangement__in=ClipArrangement.values,
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.title[:50]} ({self.start_sec:.0f}s-{self.end_sec:.0f}s)'

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
    fit_mode = models.CharField(
        max_length=10,
        choices=FitMode.choices,
        default=FitMode.CROP,
    )
    foreground_treatment = models.CharField(
        max_length=20,
        choices=ForegroundTreatment.choices,
        default=ForegroundTreatment.FILL,
    )
    background_mode = models.CharField(
        max_length=20,
        choices=BackgroundMode.choices,
        default=BackgroundMode.SOLID,
    )
    background_color = models.CharField(
        max_length=7,
        default=DEFAULT_BACKGROUND_COLOR,
    )
    blur_strength = models.PositiveSmallIntegerField(
        default=DEFAULT_BLUR_STRENGTH,
    )
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
            models.CheckConstraint(
                name='clips_cliplayoutconfig_fit_mode_valid',
                condition=models.Q(fit_mode__in=FitMode.values),
            ),
            models.CheckConstraint(
                name='clips_cliplayoutconfig_foreground_treatment_valid',
                condition=models.Q(
                    foreground_treatment__in=ForegroundTreatment.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_cliplayoutconfig_background_mode_valid',
                condition=models.Q(background_mode__in=BackgroundMode.values),
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
    caption_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
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
        max_length=10,
        blank=True,
        default='',
    )
    caption_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    caption_highlight_color = models.CharField(
        max_length=9,
        default='#FFD400',
    )
    caption_uppercase = models.BooleanField(default=False)
    emoji_keyword_map = models.JSONField(default=dict, blank=True)
    hook_enabled = models.BooleanField(default=True)
    hook_style = models.CharField(
        max_length=20,
        choices=HookStyle.choices,
        default=HookStyle.OVERLAY_TOP,
    )
    hook_duration_sec = models.FloatField(default=2.5)
    hook_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
    hook_size = models.PositiveIntegerField(default=60)
    hook_color = models.CharField(max_length=9, default='#FFFFFF')
    hook_bg_color = models.CharField(max_length=9, default='#CC000000')
    hook_animation = models.CharField(
        max_length=15,
        choices=OverlayAnimation.choices,
        default=OverlayAnimation.NONE,
    )
    hook_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
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
    intro_transition_duration_sec = models.FloatField(default=0.5)
    outro_transition_duration_sec = models.FloatField(default=0.5)
    intro_transition_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    outro_transition_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
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
    watermark_color = models.CharField(max_length=9, default='#FFFFFF')
    watermark_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
    watermark_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
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
    color_filter = models.CharField(
        max_length=15,
        choices=ColorFilterPreset.choices,
        default=ColorFilterPreset.NONE,
    )
    brightness = models.FloatField(default=0.0)
    contrast = models.FloatField(default=0.0)
    saturation = models.FloatField(default=0.0)
    lut_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    playback_speed = models.FloatField(default=1.0)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipstyleconfig_caption_style_valid',
                condition=models.Q(caption_style__in=CaptionStyle.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_caption_font_valid',
                condition=models.Q(caption_font__in=CaptionFont.values),
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
                name='clips_clipstyleconfig_hook_font_valid',
                condition=models.Q(hook_font__in=CaptionFont.values),
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
                name='clips_clipstyleconfig_watermark_font_valid',
                condition=models.Q(watermark_font__in=CaptionFont.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_progress_bar_position_valid',
                condition=models.Q(
                    progress_bar_position__in=ProgressBarPosition.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_hook_animation_valid',
                condition=models.Q(hook_animation__in=OverlayAnimation.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_color_filter_valid',
                condition=models.Q(color_filter__in=ColorFilterPreset.values),
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
    video_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    shape = models.CharField(
        max_length=10,
        choices=OverlayShape.choices,
        default=OverlayShape.RECTANGLE,
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    font_size = models.PositiveIntegerField(default=40)
    color = models.CharField(max_length=9, default='#FFFFFF')
    opacity = models.FloatField(default=1.0)
    font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
    font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    animation = models.CharField(
        max_length=15,
        choices=OverlayAnimation.choices,
        default=OverlayAnimation.NONE,
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_cliptimedoverlay_overlay_type_valid',
                condition=models.Q(overlay_type__in=OverlayType.values),
            ),
            models.CheckConstraint(
                name='clips_cliptimedoverlay_font_valid',
                condition=models.Q(font__in=CaptionFont.values),
            ),
            models.CheckConstraint(
                name='clips_cliptimedoverlay_shape_valid',
                condition=models.Q(shape__in=OverlayShape.values),
            ),
            models.CheckConstraint(
                name='clips_cliptimedoverlay_animation_valid',
                condition=models.Q(animation__in=OverlayAnimation.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return (
            f'Overlay "{self.text[:30]}"'
            f' ({self.start_sec:.1f}s-{self.end_sec:.1f}s)'
        )


class ClipTimedSfx(UUIDModel, TimeStampedModel):
    """A one-shot sound effect dropped at a timestamp on a clip."""

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='timed_sfx',
    )
    sfx_asset = models.ForeignKey(
        'assets.LibraryAsset',
        on_delete=models.CASCADE,
        related_name='+',
    )
    start_sec = models.FloatField()
    volume_db = models.FloatField(default=0.0)

    @override
    def __str__(self) -> str:
        return f'SFX {self.sfx_asset.name} @{self.start_sec}s'


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


class ClipCampaign(UUIDModel, TimeStampedModel):
    """Batch export / earnings grouping for clip distribution."""

    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.CASCADE,
        related_name='clip_campaigns',
    )
    name = models.CharField(max_length=120)
    status = models.CharField(
        max_length=10,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipcampaign_status_valid',
                condition=models.Q(status__in=CampaignStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.name


class ClipSource(UUIDModel, TimeStampedModel):
    """Registered video ready (or being probed) for clipping."""

    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.CASCADE,
        related_name='clip_sources',
    )
    run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='clip_sources',
    )
    campaign = models.ForeignKey(
        ClipCampaign,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='clip_sources',
    )
    source_type = models.CharField(
        max_length=10,
        choices=ClipSourceType.choices,
    )
    url = models.TextField(blank=True)
    library_asset_id = models.UUIDField(null=True, blank=True)
    title = models.CharField(max_length=300, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=ClipSourceStatus.choices,
        default=ClipSourceStatus.INGESTING,
    )
    error_message = models.TextField(blank=True)
    auto_start = models.BooleanField(default=False)
    pending_run_options = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipsource_status_valid',
                condition=models.Q(status__in=ClipSourceStatus.values),
            ),
            models.CheckConstraint(
                name='clips_clipsource_type_valid',
                condition=models.Q(source_type__in=ClipSourceType.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.title or f'ClipSource {self.id}'


class Earning(UUIDModel, TimeStampedModel):
    """Manual revenue entry tied to a clip campaign."""

    campaign = models.ForeignKey(
        ClipCampaign,
        on_delete=models.CASCADE,
        related_name='earnings',
    )
    candidate = models.ForeignKey(
        ClipCandidate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='earnings',
    )
    platform = models.CharField(max_length=30)
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal(0),
    )
    recorded_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    @override
    def __str__(self) -> str:
        return f'{self.platform} earning — {self.campaign}'


class ClipBrandTemplate(UUIDModel, TimeStampedModel):
    """Reusable visual style applied to candidates at analysis time."""

    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.CASCADE,
        related_name='clip_brand_templates',
    )
    name = models.CharField(max_length=120)
    archived = models.BooleanField(default=False)
    render_format = models.CharField(
        max_length=20,
        choices=RenderFormat.choices,
        default=RenderFormat.VERTICAL_9_16,
    )
    render_mode = models.CharField(
        max_length=20,
        choices=RenderMode.choices,
        default=RenderMode.SMART_CROP,
    )
    fit_mode = models.CharField(
        max_length=10,
        choices=FitMode.choices,
        default=FitMode.CROP,
    )
    foreground_treatment = models.CharField(
        max_length=20,
        choices=ForegroundTreatment.choices,
        default=ForegroundTreatment.FILL,
    )
    background_mode = models.CharField(
        max_length=20,
        choices=BackgroundMode.choices,
        default=BackgroundMode.SOLID,
    )
    background_color = models.CharField(
        max_length=7,
        default=DEFAULT_BACKGROUND_COLOR,
    )
    blur_strength = models.PositiveSmallIntegerField(
        default=DEFAULT_BLUR_STRENGTH,
    )
    caption_preset_key = models.CharField(max_length=40, blank=True, default='')
    logo_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    logo_position = models.CharField(
        max_length=15,
        choices=WatermarkPosition.choices,
        default=WatermarkPosition.BOTTOM_RIGHT,
    )
    logo_opacity = models.FloatField(default=0.85)
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
    music_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    music_volume_db = models.FloatField(default=-20.0)
    keyword_highlighter = models.BooleanField(default=True)
    auto_transitions = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar = ['name', 'id']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='clips_clipbrandtemplate_render_format_valid',
                condition=models.Q(render_format__in=RenderFormat.values),
            ),
            models.CheckConstraint(
                name='clips_clipbrandtemplate_render_mode_valid',
                condition=models.Q(render_mode__in=RenderMode.values),
            ),
            models.CheckConstraint(
                name='clips_clipbrandtemplate_fit_mode_valid',
                condition=models.Q(fit_mode__in=FitMode.values),
            ),
            models.CheckConstraint(
                name='clips_clipbrandtemplate_foreground_treatment_valid',
                condition=models.Q(
                    foreground_treatment__in=ForegroundTreatment.values,
                ),
            ),
            models.CheckConstraint(
                name='clips_clipbrandtemplate_background_mode_valid',
                condition=models.Q(background_mode__in=BackgroundMode.values),
            ),
            models.CheckConstraint(
                name='clips_clipbrandtemplate_logo_position_valid',
                condition=models.Q(logo_position__in=WatermarkPosition.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.name


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
