from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.core.models import BaseAbstractModel
from reelforge.core.models import PipelineStageModel
from reelforge.core.validators import pydantic_validator
from reelforge.production.choices import RenderEngine
from reelforge.production.schemas import QAResults
from reelforge.production.schemas import RenderSpec
from reelforge.production.schemas import SceneList


class SceneBreakdownJob(PipelineStageModel):
    """Scene breakdown of a script — converts script sections into timed scene dicts.
    One per ScriptJob; generated before asset creation to drive image/clip prompts.
    """

    script_job = models.OneToOneField(
        "scripts.ScriptJob",
        on_delete=models.CASCADE,
        related_name="scene_breakdown",
        verbose_name=_("Script Job"),
    )

    scenes = models.JSONField(
        _("Scenes"),
        default=list,
        blank=True,
        help_text=_("List of scene dicts driving image/clip generation"),
        validators=[pydantic_validator(SceneList)],
    )
    total_estimated_duration = models.FloatField(
        _("Total Estimated Duration (seconds)"),
        default=0.0,
    )
    scene_count = models.PositiveSmallIntegerField(
        _("Scene Count"),
        default=0,
    )
    breakdown_provider = models.CharField(
        _("Breakdown Provider"),
        max_length=50,
        blank=True,
        help_text=_("LLM provider used to generate the breakdown"),
    )
    breakdown_cost_usd = models.DecimalField(
        _("Breakdown Cost (USD)"),
        max_digits=8,
        decimal_places=6,
        default=0,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Scene Breakdown Job")
        verbose_name_plural = _("Scene Breakdown Jobs")
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["script_job"]),
        ]

    def __str__(self) -> str:
        title = self.script_job.final_title or self.script_job.topic.title_idea
        return f"SceneBreakdown: {title[:60]}"


class AudioMixJob(PipelineStageModel):
    """Audio mix job — combines voiceover with background music.
    Multiple AudioMixJobs can exist per AssetJob (one per mix attempt).
    The active mix is tracked via AudioMixJob.is_active.
    """

    asset_job = models.ForeignKey(
        "assets.AssetJob",
        on_delete=models.CASCADE,
        related_name="audio_mix_jobs",
        verbose_name=_("Asset Job"),
    )
    voiceover_run = models.ForeignKey(
        "assets.VoiceoverRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audio_mix_jobs",
        verbose_name=_("Source Voiceover Run"),
    )

    music_file = models.FileField(
        _("Music File"),
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
    mixed_audio_file = models.FileField(
        _("Mixed Audio File"),
        upload_to="assets/audio/mixed/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Final mixed audio (voiceover + music)"),
    )
    mixed_duration_sec = models.FloatField(
        _("Mixed Duration (seconds)"),
        default=0.0,
    )
    is_active = models.BooleanField(
        _("Active"),
        default=False,
        db_index=True,
        help_text=_("Whether this mix feeds into video rendering"),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Audio Mix Job")
        verbose_name_plural = _("Audio Mix Jobs")
        indexes = [
            models.Index(fields=["asset_job", "is_active"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        active = " [ACTIVE]" if self.is_active else ""
        return f"AudioMixJob{active}: {self.asset_job}"


class ProductionJob(PipelineStageModel):
    """Video rendering and post-processing.
    Takes assets from AssetJob and produces final video files.
    """

    asset_job = models.OneToOneField(
        "assets.AssetJob",
        on_delete=models.CASCADE,
        related_name="production_job",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="production_jobs",
    )

    # ── Sub-step references ─────────────────────────────────────────────────
    scene_breakdown_job = models.ForeignKey(
        "production.SceneBreakdownJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Scene Breakdown Job"),
        help_text=_("Scene breakdown that drove asset generation for this production"),
    )
    audio_mix_job = models.ForeignKey(
        "production.AudioMixJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Audio Mix Job"),
        help_text=_("Audio mix (voiceover + music) used in this production"),
    )
    selected_image_run = models.ForeignKey(
        "assets.ImageGenerationRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Image Run"),
        help_text=_("Image run whose images were used in rendering"),
    )
    selected_video_clip_run = models.ForeignKey(
        "assets.VideoClipGenerationRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Selected Video Clip Run"),
        help_text=_("Video clip run whose clips were used in rendering"),
    )

    # Render configuration
    render_engine = models.CharField(
        max_length=20,
        choices=RenderEngine.choices,
        default=RenderEngine.MOVIEPY,
    )
    render_spec = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Full render configuration consumed by VideoRenderer."),
        validators=[pydantic_validator(RenderSpec)],
    )
    resolution = models.CharField(
        max_length=20,
        default="1920x1080",
    )
    fps = models.PositiveSmallIntegerField(default=30)
    codec = models.CharField(max_length=20, default="libx264")
    crf = models.PositiveSmallIntegerField(
        default=18,
        help_text=_("Constant Rate Factor (18 = high quality)"),
    )

    # Output files
    raw_video_file = models.FileField(
        upload_to="production/raw/",
        null=True,
        blank=True,
        help_text=_("Unprocessed render"),
    )
    processed_video_file = models.FileField(
        upload_to="production/processed/",
        null=True,
        blank=True,
        help_text=_("Final video after QA fixes"),
    )
    shorts_video_file = models.FileField(
        upload_to="production/shorts/",
        null=True,
        blank=True,
        help_text=_("9:16 Shorts variant"),
    )

    # Video metadata
    video_duration_sec = models.FloatField(
        default=0.0,
        help_text=_("Final video duration in seconds"),
    )
    file_size_bytes = models.PositiveBigIntegerField(
        default=0,
        help_text=_("Final video file size in bytes"),
    )
    bitrate_kbps = models.PositiveIntegerField(default=0)

    # QA results
    qa_passed = models.BooleanField(default=False)
    qa_checks_run = models.PositiveSmallIntegerField(default=0)
    qa_checks_passed = models.PositiveSmallIntegerField(default=0)
    qa_results = models.JSONField(
        default=dict,
        help_text=_("QA check results: check_name → pass/fail."),
        validators=[pydantic_validator(QAResults)],
    )
    qa_notes = models.TextField(blank=True)

    # Shorts extraction
    shorts_start_sec = models.FloatField(
        default=0.0,
        help_text=_("Start time of shorts clip extracted from main video"),
    )
    shorts_end_sec = models.FloatField(
        default=0.0,
        help_text=_("End time of shorts clip extracted from main video"),
    )
    shorts_selection_reason = models.TextField(
        blank=True,
        help_text=_("Why this segment was chosen for shorts (hook quality, engagement, etc.)"),
    )

    # Caption files
    caption_srt_file = models.FileField(
        upload_to="production/captions/srt/",
        null=True,
        blank=True,
        help_text=_("SRT subtitle file generated by Whisper"),
    )
    caption_ass_file = models.FileField(
        upload_to="production/captions/ass/",
        null=True,
        blank=True,
        help_text=_("ASS subtitle file for FFmpeg caption burning"),
    )

    # Render performance
    render_duration_sec = models.FloatField(
        default=0.0,
        help_text=_("How long the render took in seconds"),
    )
    render_worker_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Production Job")
        verbose_name_plural = _("Production Jobs")
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["asset_job"]),
        ]

    def __str__(self) -> str:
        title = self.asset_job.script_job.final_title
        return f"Render: {title[:60]}"

    @property
    def qa_pass_rate(self) -> float:
        """Percentage of QA checks that passed."""
        if self.qa_checks_run == 0:
            return 0.0
        return (self.qa_checks_passed / self.qa_checks_run) * 100

    @property
    def file_size_mb(self) -> float:
        """File size in MB for display."""
        if self.file_size_bytes:
            return self.file_size_bytes / (1024 * 1024)
        return 0.0

    @property
    def shorts_duration_sec(self) -> float:
        """Duration of shorts clip."""
        return self.shorts_end_sec - self.shorts_start_sec

    @property
    def has_shorts(self) -> bool:
        """Whether a shorts clip was extracted."""
        return bool(self.shorts_video_file) or (self.shorts_end_sec > self.shorts_start_sec)
