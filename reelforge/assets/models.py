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


class RunStatus(models.TextChoices):
    """Status for individual execution attempt records (not FSM — plain CharField)."""

    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class AssetJob(PipelineStageModel):
    """Asset generation job for a script.
    Manages voiceover generation, background images, thumbnails, and music selection.
    Uses FSM for overall job status, individual status fields for each asset type.
    Individual sub-steps track their execution attempts via *Run sibling records.
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

    # ── Selected Runs (set automatically on first completion, or by operator) ──
    selected_voiceover_run = models.ForeignKey(
        "assets.VoiceoverRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Voiceover Run"),
        help_text=_("The voiceover run whose merged audio feeds downstream rendering"),
    )
    selected_image_run = models.ForeignKey(
        "assets.ImageGenerationRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Image Run"),
        help_text=_("The image generation run whose images feed downstream rendering"),
    )
    selected_video_clip_run = models.ForeignKey(
        "assets.VideoClipGenerationRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Video Clip Run"),
        help_text=_("The video clip run whose clips feed downstream rendering"),
    )
    selected_thumbnail_run = models.ForeignKey(
        "assets.ThumbnailRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Thumbnail Run"),
        help_text=_("The thumbnail run whose options feed the distribution step"),
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
    voiceover_run = models.ForeignKey(
        "assets.VoiceoverRun",
        on_delete=models.CASCADE,
        related_name="segments",
        verbose_name=_("Voiceover Run"),
        null=True,
        blank=True,
        help_text=_("The specific voiceover run this segment belongs to"),
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
        max_digits=10,
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
    image_run = models.ForeignKey(
        "assets.ImageGenerationRun",
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("Image Generation Run"),
        null=True,
        blank=True,
        help_text=_("The specific image generation run this image belongs to"),
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
        max_digits=10,
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
    thumbnail_run = models.ForeignKey(
        "assets.ThumbnailRun",
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name=_("Thumbnail Run"),
        null=True,
        blank=True,
        help_text=_("The specific thumbnail run this option belongs to"),
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
        max_digits=10,
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


# ── Run Models ─────────────────────────────────────────────────────────────────
# Each Run model represents a single execution attempt of a sub-step.
# Previous runs are never deleted — the AssetJob.selected_*_run FK tracks
# which run feeds downstream processing.


class VoiceoverRun(BaseAbstractModel):
    """Single voiceover generation attempt for an AssetJob.
    Multiple runs can exist; AssetJob.selected_voiceover_run tracks which is active.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="voiceover_runs",
        verbose_name=_("Asset Job"),
    )
    run_number = models.PositiveSmallIntegerField(
        _("Run Number"),
        help_text=_("Sequential attempt number (1, 2, 3…)"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=RunStatus,
        default=RunStatus.PENDING,
        db_index=True,
    )
    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
        help_text=_("TTS provider used (e.g., elevenlabs, openai_tts)"),
    )
    voice_id = models.CharField(
        _("Voice ID"),
        max_length=255,
        blank=True,
    )
    merged_audio_file = models.FileField(
        _("Merged Audio File"),
        upload_to="assets/audio/full/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Combined voiceover audio for this run"),
    )
    total_duration_sec = models.FloatField(
        _("Total Duration (seconds)"),
        default=0.0,
    )
    total_cost_usd = models.DecimalField(
        _("Total Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )
    celery_task_id = models.CharField(
        _("Celery Task ID"),
        max_length=255,
        blank=True,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset_job", "run_number"]
        verbose_name = _("Voiceover Run")
        verbose_name_plural = _("Voiceover Runs")
        unique_together = [["asset_job", "run_number"]]
        indexes = [
            models.Index(fields=["asset_job", "run_number"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"VoiceoverRun #{self.run_number} [{self.status}] — {self.asset_job}"


class ImageGenerationRun(BaseAbstractModel):
    """Single image generation attempt for an AssetJob.
    Multiple runs can exist; AssetJob.selected_image_run tracks which is active.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="image_runs",
        verbose_name=_("Asset Job"),
    )
    run_number = models.PositiveSmallIntegerField(
        _("Run Number"),
        help_text=_("Sequential attempt number (1, 2, 3…)"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=RunStatus,
        default=RunStatus.PENDING,
        db_index=True,
    )
    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
    )
    images_count = models.PositiveSmallIntegerField(
        _("Images Count"),
        default=0,
    )
    total_cost_usd = models.DecimalField(
        _("Total Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )
    generation_config = models.JSONField(
        _("Generation Config"),
        default=dict,
        blank=True,
        help_text=_("Prompts, size, style params used for this run"),
    )
    celery_task_id = models.CharField(
        _("Celery Task ID"),
        max_length=255,
        blank=True,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset_job", "run_number"]
        verbose_name = _("Image Generation Run")
        verbose_name_plural = _("Image Generation Runs")
        unique_together = [["asset_job", "run_number"]]
        indexes = [
            models.Index(fields=["asset_job", "run_number"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"ImageGenerationRun #{self.run_number} [{self.status}] — {self.asset_job}"


class VideoClipGenerationRun(BaseAbstractModel):
    """Single video clip animation attempt for an AssetJob.
    Animates still images from a given ImageGenerationRun into short clips.
    Multiple runs can exist; AssetJob.selected_video_clip_run tracks which is active.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="video_clip_runs",
        verbose_name=_("Asset Job"),
    )
    run_number = models.PositiveSmallIntegerField(
        _("Run Number"),
        help_text=_("Sequential attempt number (1, 2, 3…)"),
    )
    image_run = models.ForeignKey(
        ImageGenerationRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_clip_runs",
        verbose_name=_("Source Image Run"),
        help_text=_("Which image run's images were animated"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=RunStatus,
        default=RunStatus.PENDING,
        db_index=True,
    )
    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
    )
    clips_count = models.PositiveSmallIntegerField(
        _("Clips Count"),
        default=0,
    )
    total_cost_usd = models.DecimalField(
        _("Total Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )
    generation_config = models.JSONField(
        _("Generation Config"),
        default=dict,
        blank=True,
        help_text=_("Prompts, duration, provider params used for this run"),
    )
    celery_task_id = models.CharField(
        _("Celery Task ID"),
        max_length=255,
        blank=True,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset_job", "run_number"]
        verbose_name = _("Video Clip Generation Run")
        verbose_name_plural = _("Video Clip Generation Runs")
        unique_together = [["asset_job", "run_number"]]
        indexes = [
            models.Index(fields=["asset_job", "run_number"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"VideoClipGenerationRun #{self.run_number} [{self.status}] — {self.asset_job}"


class ThumbnailRun(BaseAbstractModel):
    """Single thumbnail generation attempt for an AssetJob.
    Multiple runs can exist; AssetJob.selected_thumbnail_run tracks which is active.
    """

    asset_job = models.ForeignKey(
        AssetJob,
        on_delete=models.CASCADE,
        related_name="thumbnail_runs",
        verbose_name=_("Asset Job"),
    )
    run_number = models.PositiveSmallIntegerField(
        _("Run Number"),
        help_text=_("Sequential attempt number (1, 2, 3…)"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=RunStatus,
        default=RunStatus.PENDING,
        db_index=True,
    )
    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
    )
    options_count = models.PositiveSmallIntegerField(
        _("Options Count"),
        default=0,
    )
    total_cost_usd = models.DecimalField(
        _("Total Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )
    celery_task_id = models.CharField(
        _("Celery Task ID"),
        max_length=255,
        blank=True,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset_job", "run_number"]
        verbose_name = _("Thumbnail Run")
        verbose_name_plural = _("Thumbnail Runs")
        unique_together = [["asset_job", "run_number"]]
        indexes = [
            models.Index(fields=["asset_job", "run_number"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"ThumbnailRun #{self.run_number} [{self.status}] — {self.asset_job}"


class GeneratedVideoClip(BaseAbstractModel):
    """Individual animated video clip produced by a VideoClipGenerationRun."""

    video_clip_run = models.ForeignKey(
        VideoClipGenerationRun,
        on_delete=models.CASCADE,
        related_name="clips",
        verbose_name=_("Video Clip Run"),
    )
    position_idx = models.PositiveSmallIntegerField(
        _("Position Index"),
        help_text=_("Order of this clip in the video timeline"),
    )
    source_image = models.ForeignKey(
        GeneratedImage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_clips",
        verbose_name=_("Source Image"),
        help_text=_("The still image that was animated into this clip"),
    )
    prompt_used = models.TextField(
        _("Prompt Used"),
        help_text=_("Animation prompt used to generate this clip"),
    )
    clip_file = models.FileField(
        _("Clip File"),
        upload_to="assets/clips/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Generated video clip file (MP4)"),
    )
    duration_sec = models.FloatField(
        _("Duration (seconds)"),
        default=0.0,
    )
    provider = models.CharField(
        _("Provider"),
        max_length=50,
        blank=True,
    )
    is_selected = models.BooleanField(
        _("Selected"),
        default=True,
        help_text=_("Whether this clip is selected for rendering"),
    )
    generation_cost_usd = models.DecimalField(
        _("Generation Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )

    class Meta:
        ordering = ["video_clip_run", "position_idx"]
        verbose_name = _("Generated Video Clip")
        verbose_name_plural = _("Generated Video Clips")
        unique_together = [["video_clip_run", "position_idx"]]
        indexes = [
            models.Index(fields=["video_clip_run", "position_idx"]),
            models.Index(fields=["is_selected"]),
        ]

    def __str__(self) -> str:
        return f"Clip {self.position_idx}: {self.prompt_used[:50]}…"
