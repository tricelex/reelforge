from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from reelforge.core.models import BaseAbstractModel
from reelforge.core.models import PipelineStageModel
from reelforge.core.validators import pydantic_validator
from reelforge.scripts.schemas import BRollSuggestions
from reelforge.scripts.schemas import ChapterList
from reelforge.scripts.schemas import GeneratedHooks
from reelforge.scripts.schemas import Hook
from reelforge.scripts.schemas import QAIssueList
from reelforge.scripts.schemas import ResearchData
from reelforge.scripts.schemas import ResearchSourceList
from reelforge.scripts.schemas import ScriptQualityFlagsSchema
from reelforge.scripts.schemas import ScriptSectionList
from reelforge.scripts.schemas import SegmentList


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
        validators=[pydantic_validator(ResearchData)],
    )
    research_sources = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Sources used in script with URL, title, and key claim."),
        validators=[pydantic_validator(ResearchSourceList)],
    )

    # Generated hooks (agent creates multiple options, operator selects best)
    generated_hooks = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Agent-generated hook variations for the video opening."),
        validators=[pydantic_validator(GeneratedHooks)],
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
        blank=True,
        help_text=_("Key points covered in script"),
    )
    sections = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Parsed script sections with per-section narration and b-roll indices."),
        validators=[pydantic_validator(ScriptSectionList)],
    )

    # Quality gate
    ready_for_production = models.BooleanField(
        default=False,
        help_text=_("True when agent self-review passes all quality checks."),
    )
    revision_notes = models.TextField(
        blank=True,
        help_text=_("Agent explanation if ready_for_production is False."),
    )
    quality_flags = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Agent quality self-assessment (hook_score, faceless_compliance, etc.)."),
        validators=[pydantic_validator(ScriptQualityFlagsSchema)],
    )

    # QA tracking
    readability_score = models.FloatField(
        default=0.0,
        help_text=_("0-10 readability score (Flesch-Kincaid equivalent)"),
    )
    qa_issues_found = models.JSONField(
        default=list,
        blank=True,
        help_text=_("QA issues found in the script."),
        validators=[pydantic_validator(QAIssueList)],
    )
    qa_issues_fixed = models.JSONField(
        default=list,
        blank=True,
        help_text=_("QA issues that have been resolved."),
        validators=[pydantic_validator(QAIssueList)],
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
        blank=True,
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("YouTube category (e.g., 'Education', 'Howto & Style')"),
    )
    chapters = models.JSONField(
        default=list,
        blank=True,
        help_text=_("YouTube chapter markers for the video."),
        validators=[pydantic_validator(ChapterList)],
    )
    pinned_comment = models.TextField(
        blank=True,
        help_text=_("Comment to pin on video"),
    )
    thumbnail_text = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("2-5 word overlay text for thumbnail generation agent."),
    )
    thumbnail_emotion = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Single emotion word for thumbnail style (e.g. shock, curiosity)."),
    )
    search_hashtags = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
        help_text=_("3-5 hashtags for video description footer."),
    )

    # B-roll suggestions (structured for AssetJob)
    broll_suggestions = models.JSONField(
        default=list,
        blank=True,
        help_text=_("B-roll cues consumed by AssetJob for image generation."),
        validators=[pydantic_validator(BRollSuggestions)],
    )

    # TTS segments (pre-chunked for parallel generation)
    segments = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Pre-chunked TTS segments driving VoiceoverSegment creation."),
        validators=[pydantic_validator(SegmentList)],
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
    def selected_hook(self) -> Hook | None:
        """Returns the currently selected hook from generated_hooks list."""
        hooks = self.generated_hooks if isinstance(self.generated_hooks, list) else []
        if hooks and len(hooks) > self.selected_hook_idx:
            return Hook.model_validate(hooks[self.selected_hook_idx])
        return None

    @property
    def revision_count(self) -> int:
        """Count of script revisions."""
        return self.revisions.count()

    @property
    def total_segments(self) -> int:
        """Count of TTS segments."""
        return len(self.segments) if isinstance(self.segments, list) else 0

    @property
    def broll_count(self) -> int:
        """Count of B-roll suggestions."""
        return len(self.broll_suggestions) if isinstance(self.broll_suggestions, list) else 0


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
