from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.core.models import BaseAbstractModel
from reelforge.core.models import PipelineStageModel


class ScriptJob(PipelineStageModel):
    """A script generation job for a single video.
    Linked to an approved TopicIdea.
    Produces ScriptRevision instances.
    """

    topic = models.OneToOneField(
        "research.TopicIdea",
        on_delete=models.CASCADE,
        related_name="script_job",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="script_jobs",
    )

    # Research gathered by agent
    research_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Facts, stats, sources gathered during script research"),
    )
    research_sources = ArrayField(
        models.URLField(),
        default=list,
        help_text=_("URLs of sources used in script"),
    )

    # Generated hooks (agent creates multiple options, operator selects best)
    generated_hooks = models.JSONField(
        default=list,
        blank=True,
        help_text=_('[{"text": "...", "type": "question|statement|story", "score": 8.5}, ...]'),
    )
    selected_hook_idx = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Index of selected hook in generated_hooks array"),
    )
    hook_score = models.FloatField(
        default=0.0,
        help_text=_("0-10 hook quality score from agent"),
    )

    # Script content (current version)
    script_text = models.TextField(blank=True)
    script_version = models.PositiveSmallIntegerField(
        default=1,
        help_text=_("Current version number (increments on major changes)"),
    )
    script_file = models.FileField(
        upload_to="scripts/",
        null=True,
        blank=True,
        help_text=_("Exported script file for download/archive"),
    )
    word_count = models.PositiveIntegerField(default=0)
    estimated_duration_mins = models.FloatField(
        default=0.0,
        help_text=_("Estimated video duration based on word count"),
    )

    # Script structure
    main_points = ArrayField(
        models.TextField(),
        default=list,
        help_text=_("Key points covered in script"),
    )

    # QA tracking
    readability_score = models.FloatField(
        default=0.0,
        help_text=_("0-10 readability score (Flesch-Kincaid equivalent)"),
    )
    qa_issues_found = models.JSONField(
        default=list,
        blank=True,
        help_text=_('[{"issue": "long sentence", "location": "para 3", "severity": "low"}, ...]'),
    )
    qa_issues_fixed = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Issues that have been resolved"),
    )

    # SEO metadata
    final_title = models.CharField(max_length=200, blank=True)
    final_description = models.TextField(
        blank=True,
        help_text=_("YouTube video description"),
    )
    seo_tags = ArrayField(
        models.CharField(max_length=100),
        default=list,
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("YouTube category (e.g., 'Education', 'Howto & Style')"),
    )
    chapters = models.JSONField(
        default=list,
        help_text=_('[{"timestamp": "0:00", "title": "Introduction"}, ...]'),
    )
    pinned_comment = models.TextField(
        blank=True,
        help_text=_("Comment to pin on video"),
    )

    # B-roll suggestions (structured for AssetJob)
    broll_suggestions = models.JSONField(
        default=list,
        blank=True,
        help_text=_('[{"timestamp_approx": 15, "description": "Show chart of rising prices"}, ...]'),
    )

    # TTS segments (pre-chunked for parallel generation)
    segments = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            '[{"segment_id": 1, "text": "...", "section": "intro", "approx_start_sec": 0, "approx_end_sec": 15}, ...]'
        ),
    )

    # Approval
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_scripts",
    )
    auto_approved = models.BooleanField(
        default=False,
        help_text=_("True if approved automatically after delay"),
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Script Job")
        verbose_name_plural = _("Script Jobs")
        indexes = [
            models.Index(fields=["status", "approved"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self) -> str:
        title = self.final_title or self.topic.title_idea
        return f"Script: {title[:60]}"

    @property
    def selected_hook(self) -> dict[str, str | float]:
        """Returns the currently selected hook from generated_hooks array."""
        if self.generated_hooks and len(self.generated_hooks) > self.selected_hook_idx:
            return self.generated_hooks[self.selected_hook_idx]
        return {}

    @property
    def revision_count(self) -> int:
        """Count of script revisions."""
        return self.revisions.count()

    @property
    def total_segments(self) -> int:
        """Count of TTS segments."""
        return len(self.segments) if self.segments else 0

    @property
    def broll_count(self) -> int:
        """Count of B-roll suggestions."""
        return len(self.broll_suggestions) if self.broll_suggestions else 0


class ScriptRevision(BaseAbstractModel):
    """Version history for a script.
    Each agent iteration or manual edit creates a new revision.
    """

    script_job = models.ForeignKey(
        ScriptJob,
        on_delete=models.CASCADE,
        related_name="revisions",
    )

    version_number = models.PositiveSmallIntegerField(default=1)
    script_text = models.TextField()
    word_count = models.PositiveIntegerField(default=0)
    change_summary = models.TextField(
        blank=True,
        help_text=_("What changed in this revision"),
    )
    changed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="script_revisions",
    )
    agent_feedback = models.TextField(
        blank=True,
        help_text=_("Agent evaluation of this revision"),
    )

    class Meta:
        ordering = ["-version_number"]
        verbose_name = _("Script Revision")
        verbose_name_plural = _("Script Revisions")
        unique_together = ["script_job", "version_number"]
        indexes = [
            models.Index(fields=["script_job", "version_number"]),
        ]

    def __str__(self) -> str:
        return f"v{self.version_number} - {self.script_job.topic.title_idea[:40]}"
