from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.assets.choices import AnimationType
from reelforge.assets.choices import AssetStatus
from reelforge.core.models import BaseAbstractModel
from reelforge.core.models import PipelineStageModel


class AssetJob(PipelineStageModel):
    """Coordinates generation of all assets for a video:
    - Voiceover (TTS segments)
    - Images (B-roll)
    - Background music
    - Thumbnail options
    """

    script_job = models.OneToOneField(
        "scripts.ScriptJob",
        on_delete=models.CASCADE,
        related_name="asset_job",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="asset_jobs",
    )

    # Voiceover
    voiceover_provider = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("TTS provider used (elevenlabs, openai_tts, etc.)"),
    )
    voiceover_status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    voiceover_file = models.FileField(
        upload_to="audio/full/",
        null=True,
        blank=True,
        help_text=_("Final merged voiceover MP3"),
    )
    voiceover_duration_seconds = models.FloatField(default=0.0)
    voiceover_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    # Images
    images_provider = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Image provider used (fal_ai, replicate, dalle, etc.)"),
    )
    images_status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    images_generated_count = models.PositiveSmallIntegerField(default=0)
    images_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    # Music
    music_file = models.FileField(
        upload_to="audio/music/",
        null=True,
        blank=True,
    )
    music_url = models.URLField(
        blank=True,
        help_text=_("URL to royalty-free music track"),
    )
    music_title = models.CharField(max_length=255, blank=True)
    music_style = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Music genre/style (cinematic, upbeat, calm, etc.)"),
    )
    music_volume_pct = models.FloatField(
        default=0.08,
        help_text=_("Music volume as percentage of voiceover (0.08 = 8%)"),
    )
    music_status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )

    # Thumbnails
    thumbnails_status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    thumbnails_generated_count = models.PositiveSmallIntegerField(default=0)
    selected_thumbnail = models.FileField(
        upload_to="thumbnails/selected/",
        null=True,
        blank=True,
    )
    thumbnails_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    # Visual timeline (master coordination layer for video rendering)
    visual_timeline = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            "Master timeline coordinating all assets: "
            '[{"start_ms": 0, "end_ms": 15000, "image_file_id": "...", '
            '"segment_text": "...", "section": "intro", "animation_type": "KEN_BURNS"}, ...]'
        ),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Asset Job")
        verbose_name_plural = _("Asset Jobs")
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["script_job"]),
        ]

    def __str__(self) -> str:
        return f"Assets: {self.script_job.final_title[:60]}"

    @property
    def total_cost_usd(self) -> float:
        return float(
            self.voiceover_cost_usd + self.images_cost_usd + self.thumbnails_cost_usd,
        )

    @property
    def all_assets_ready(self) -> bool:
        return (
            self.voiceover_status == AssetStatus.COMPLETED
            and self.images_status == AssetStatus.COMPLETED
            and self.thumbnails_status == AssetStatus.COMPLETED
        )


class VoiceoverSegment(BaseAbstractModel):
    """A single TTS segment of the voiceover.
    Script is split into segments for parallel generation.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="voiceover_segments",
    )

    segment_index = models.PositiveSmallIntegerField()
    text = models.TextField()
    section = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Script section (intro, body, outro, etc.)"),
    )
    audio_file = models.FileField(
        upload_to="audio/segments/",
        null=True,
        blank=True,
    )
    duration_seconds = models.FloatField(default=0.0)
    start_ms = models.PositiveIntegerField(
        default=0,
        help_text=_("Start position in merged full audio (milliseconds)"),
    )
    end_ms = models.PositiveIntegerField(
        default=0,
        help_text=_("End position in merged full audio (milliseconds)"),
    )
    status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    tts_provider = models.CharField(max_length=50, blank=True)
    tts_voice_id = models.CharField(max_length=100, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    class Meta:
        ordering = ["segment_index"]
        verbose_name = _("Voiceover Segment")
        verbose_name_plural = _("Voiceover Segments")
        unique_together = ["asset_job", "segment_index"]
        indexes = [
            models.Index(fields=["asset_job", "segment_index"]),
        ]

    def __str__(self) -> str:
        return f"Segment {self.segment_index}: {self.text[:50]}"


class GeneratedImage(BaseAbstractModel):
    """A single B-roll image generated for the video."""

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="images",
    )

    position_index = models.PositiveSmallIntegerField(
        help_text=_("Order in video timeline"),
    )
    prompt = models.TextField(help_text=_("Image generation prompt"))
    image_file = models.ImageField(
        upload_to="images/",
        null=True,
        blank=True,
    )
    is_selected = models.BooleanField(
        default=True,
        help_text=_("Whether to use this image in final video"),
    )
    section = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Script section this image belongs to"),
    )
    timestamp_approx = models.CharField(
        max_length=20,
        blank=True,
        help_text=_("Approximate timestamp (e.g., '1:23', '0:45')"),
    )
    animation_type = models.CharField(
        max_length=20,
        choices=AnimationType.choices,
        default=AnimationType.KEN_BURNS,
    )
    duration_seconds = models.FloatField(default=5.0)
    status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    image_provider = models.CharField(max_length=50, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    class Meta:
        ordering = ["position_index"]
        verbose_name = _("Generated Image")
        verbose_name_plural = _("Generated Images")
        indexes = [
            models.Index(fields=["asset_job", "position_index"]),
        ]

    def __str__(self) -> str:
        return f"Image {self.position_index}: {self.prompt[:50]}"


class ThumbnailOption(BaseAbstractModel):
    """A thumbnail candidate.
    Agent generates 3-5 options, operator picks one.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="thumbnail_options",
    )

    option_number = models.PositiveSmallIntegerField()
    prompt = models.TextField()
    image_file = models.ImageField(
        upload_to="thumbnails/options/",
        null=True,
        blank=True,
    )
    is_selected = models.BooleanField(default=False)
    ctr_score = models.FloatField(
        default=0.0,
        help_text=_("AI-predicted CTR potential (0-10)"),
    )
    status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.PENDING,
    )
    image_provider = models.CharField(max_length=50, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
    )

    class Meta:
        ordering = ["option_number"]
        verbose_name = _("Thumbnail Option")
        verbose_name_plural = _("Thumbnail Options")
        unique_together = ["asset_job", "option_number"]
        indexes = [
            models.Index(fields=["asset_job", "is_selected"]),
        ]

    def __str__(self) -> str:
        selected = " [SELECTED]" if self.is_selected else ""
        return f"Thumbnail {self.option_number}{selected}"
