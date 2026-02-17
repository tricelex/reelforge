from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.core.models import PipelineStageModel
from reelforge.production.choices import RenderEngine


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

    # Render configuration
    render_engine = models.CharField(
        max_length=20,
        choices=RenderEngine.choices,
        default=RenderEngine.MOVIEPY,
    )
    render_spec = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Full render specification with all settings, effects, transitions"),
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
        help_text=_("QA check results: {audio_sync: bool, no_black_frames: bool, duration_ok: bool, ...}"),
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
