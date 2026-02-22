from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.assets.schemas import VisualTimeline
from reelforge.core.models import BaseAbstractModel
from reelforge.core.models import PipelineStageModel
from reelforge.core.validators import pydantic_validator


class AssetStatusChoices(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    GENERATING = "GENERATING", _("Generating")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class AssetJob(PipelineStageModel):
    """Asset generation job for a script.
    Manages voiceover generation, background images, thumbnails, and music selection.
    Uses FSM for overall job status, individual status fields for each asset type.
    """

    script_job = models.OneToOneField(
        "scripts.ScriptJob",
        on_delete=models.CASCADE,
        related_name="asset_job",
        verbose_name=_("Script Job"),
    )

    # ── Voiceover ──────────────────────────────────────────────────────────
    voiceover_provider = models.CharField(
        _("Voiceover Provider"),
        max_length=50,
        blank=True,
        help_text=_("TTS provider used (e.g., elevenlabs, openai_tts)"),
    )

    voiceover_full_file = models.FileField(
        _("Full Voiceover File"),
        upload_to="assets/audio/full/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Merged full voiceover audio file"),
    )

    voiceover_duration_sec = models.FloatField(
        _("Voiceover Duration (seconds)"),
        default=0.0,
        help_text=_("Total duration of all voiceover segments combined"),
    )

    voiceover_status = models.CharField(
        _("Voiceover Status"),
        max_length=20,
        choices=AssetStatusChoices,
        default=AssetStatusChoices.PENDING,
    )

    voiceover_cost_usd = models.DecimalField(
        _("Voiceover Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
        help_text=_("Total cost for voiceover generation"),
    )

    # ── Music ──────────────────────────────────────────────────────────────
    music_file = models.FileField(
        _("Background Music File"),
        upload_to="assets/music/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Selected background music track"),
    )

    music_style = models.CharField(
        _("Music Style"),
        max_length=100,
        blank=True,
        help_text=_("Style of background music (e.g., inspiring_cinematic, calm_ambient)"),
    )

    music_volume_pct = models.FloatField(
        _("Music Volume (%)"),
        default=0.08,
        help_text=_("Background music volume as percentage of voiceover volume"),
    )

    music_status = models.CharField(
        _("Music Status"),
        max_length=20,
        choices=AssetStatusChoices,
        default=AssetStatusChoices.PENDING,
    )

    # ── Images ─────────────────────────────────────────────────────────────
    images_status = models.CharField(
        _("Images Status"),
        max_length=20,
        choices=AssetStatusChoices,
        default=AssetStatusChoices.PENDING,
    )

    images_provider = models.CharField(
        _("Image Provider"),
        max_length=50,
        blank=True,
        help_text=_("Image generation provider used (e.g., fal_ai, replicate)"),
    )

    images_count = models.PositiveSmallIntegerField(
        _("Images Count"),
        default=0,
        help_text=_("Number of background images generated"),
    )

    images_cost_usd = models.DecimalField(
        _("Images Cost (USD)"),
        max_digits=8,
        decimal_places=4,
        default=0,
        help_text=_("Total cost for image generation"),
    )

    # ── Thumbnails ─────────────────────────────────────────────────────────
    thumbnails_status = models.CharField(
        _("Thumbnails Status"),
        max_length=20,
        choices=AssetStatusChoices,
        default=AssetStatusChoices.PENDING,
    )

    selected_thumbnail = models.FileField(
        _("Selected Thumbnail"),
        upload_to="assets/thumbnails/selected/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("The thumbnail selected for the video"),
    )

    # ── Timeline ───────────────────────────────────────────────────────────
    visual_timeline = models.JSONField(
        default=list,
        verbose_name=_("Visual Timeline"),
        blank=True,
        help_text=_("Composited timeline driving VideoRenderer — maps time windows to images."),
        validators=[pydantic_validator(VisualTimeline)],
    )

    # ── Costs ──────────────────────────────────────────────────────────────
    total_cost_usd = models.DecimalField(
        _("Total Cost (USD)"),
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text=_("Total cost for all asset generation (voiceover + images + thumbnails)"),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Asset Job")
        verbose_name_plural = _("Asset Jobs")
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["script_job"]),
        ]

    def __str__(self) -> str:
        return f"AssetJob: {self.script_job.final_title or self.script_job.topic.title_idea}"

    @property
    def channel(self):
        """Convenience accessor to channel via script_job."""
        return self.script_job.topic.channel

    @property
    def total_images_count(self) -> int:
        """Total number of images generated for this asset job."""
        return self.images.count()


class VoiceoverSegment(BaseAbstractModel):
    """Individual voiceover segment for a script section."""

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="voiceover_segments",
        verbose_name=_("Asset Job"),
    )

    segment_id = models.PositiveSmallIntegerField(
        _("Segment ID"),
        help_text=_("Order of this segment in the full script"),
    )

    text = models.TextField(
        _("Script Text"),
        help_text=_("Text that was converted to speech for this segment"),
    )

    section = models.CharField(
        _("Script Section"),
        max_length=50,
        blank=True,
        help_text=_("Script section (e.g., HOOK, INTRO_BRIDGE, SECTION_1, OUTRO_CTA)"),
    )

    audio_file = models.FileField(
        _("Audio File"),
        upload_to="assets/audio/segments/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Generated audio file for this segment"),
    )

    duration_sec = models.FloatField(
        _("Duration (seconds)"),
        default=0.0,
        help_text=_("Duration of this audio segment"),
    )

    # Timeline position in merged audio
    start_ms = models.PositiveIntegerField(
        _("Start Time (ms)"),
        default=0,
        help_text=_("Start position in full merged voiceover (milliseconds)"),
    )

    end_ms = models.PositiveIntegerField(
        _("End Time (ms)"),
        default=0,
        help_text=_("End position in full merged voiceover (milliseconds)"),
    )

    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=AssetStatusChoices,
        default=AssetStatusChoices.PENDING,
    )

    # Provider metadata
    tts_provider_used = models.CharField(
        _("TTS Provider"),
        max_length=50,
        blank=True,
        help_text=_("TTS provider used to generate this segment"),
    )

    voice_id_used = models.CharField(
        _("Voice ID"),
        max_length=255,
        blank=True,
        help_text=_("Voice ID used for this segment"),
    )

    generation_cost_usd = models.DecimalField(
        _("Generation Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
        help_text=_("Cost to generate this segment"),
    )

    class Meta:
        ordering = ["asset_job", "segment_id"]
        verbose_name = _("Voiceover Segment")
        verbose_name_plural = _("Voiceover Segments")
        unique_together = [["asset_job", "segment_id"]]
        indexes = [
            models.Index(fields=["asset_job", "segment_id"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"Segment {self.segment_id}: {self.text[:50]}..."


class GeneratedImage(BaseAbstractModel):
    """Background image generated for a script section."""

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("Asset Job"),
    )

    position_idx = models.PositiveSmallIntegerField(
        _("Position Index"),
        help_text=_("Order of this image in the video timeline"),
    )

    prompt_used = models.TextField(
        _("Prompt Used"),
        help_text=_("Image generation prompt used"),
    )

    image_file = models.FileField(
        _("Image File"),
        upload_to="assets/images/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Generated background image"),
    )

    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
        help_text=_("Image generation provider used"),
    )

    is_selected = models.BooleanField(
        _("Selected"),
        default=True,
        help_text=_("Whether this image option was selected for the video"),
    )

    section = models.CharField(
        _("Script Section"),
        max_length=50,
        blank=True,
        help_text=_("Script section this image is associated with"),
    )

    timestamp_approx = models.CharField(
        _("Approximate Timestamp"),
        max_length=20,
        blank=True,
        help_text=_("Approximate timestamp in video (e.g., '0:45', '2:30')"),
    )

    generation_cost_usd = models.DecimalField(
        _("Generation Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
        help_text=_("Cost to generate this image"),
    )

    class Meta:
        ordering = ["asset_job", "position_idx"]
        verbose_name = _("Generated Image")
        verbose_name_plural = _("Generated Images")
        indexes = [
            models.Index(fields=["asset_job", "position_idx"]),
            models.Index(fields=["is_selected"]),
        ]

    def __str__(self) -> str:
        return f"Image {self.position_idx}: {self.prompt_used[:50]}..."


class ThumbnailOption(BaseAbstractModel):
    """Thumbnail option generated for the video."""

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="thumbnails",
        verbose_name=_("Asset Job"),
    )

    option_number = models.PositiveSmallIntegerField(
        _("Option Number"),
        help_text=_("Thumbnail option number (0, 1, 2)"),
    )

    image_file = models.FileField(
        _("Thumbnail Image"),
        upload_to="assets/thumbnails/options/%Y/%m/%d/",
        help_text=_("Generated thumbnail image"),
    )

    prompt_used = models.TextField(
        _("Prompt Used"),
        blank=True,
        help_text=_("Thumbnail generation prompt used"),
    )

    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
        help_text=_("Image generation provider used"),
    )

    is_selected = models.BooleanField(
        _("Selected"),
        default=False,
        help_text=_("Whether this thumbnail was selected for the video"),
    )

    ctr_score = models.FloatField(
        _("CTR Score"),
        default=0.0,
        help_text=_("AI-predicted click-through rate potential (0-10)"),
    )

    generation_cost_usd = models.DecimalField(
        _("Generation Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
        help_text=_("Cost to generate this thumbnail"),
    )

    class Meta:
        ordering = ["asset_job", "option_number"]
        verbose_name = _("Thumbnail Option")
        verbose_name_plural = _("Thumbnail Options")
        indexes = [
            models.Index(fields=["asset_job", "is_selected"]),
            models.Index(fields=["-ctr_score"]),
        ]

    def __str__(self) -> str:
        selected = " [SELECTED]" if self.is_selected else ""
        return f"Thumbnail {self.option_number}{selected}"
