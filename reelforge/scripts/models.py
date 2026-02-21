from __future__ import annotations

from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from ***REMOVED***.core.fields import PydanticField
from ***REMOVED***.core.models import BaseAbstractModel
from ***REMOVED***.core.models import PipelineStageModel
from ***REMOVED***.scripts.schemas import BRollSuggestions
from ***REMOVED***.scripts.schemas import ChapterList
from ***REMOVED***.scripts.schemas import GeneratedHooks
from ***REMOVED***.scripts.schemas import Hook
from ***REMOVED***.scripts.schemas import QAIssueList
from ***REMOVED***.scripts.schemas import ResearchData
from ***REMOVED***.scripts.schemas import SegmentList


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
    research_data = PydanticField(
        schema=ResearchData,
        default=ResearchData,
        blank=True,
        help_text=_("Facts, stats, sources gathered during script research"),
    )
    research_sources = ArrayField(
        models.URLField(),
        default=list,
        help_text=_("URLs of sources used in script"),
    )

    # Generated hooks (agent creates multiple options, operator selects best)
    generated_hooks = PydanticField(
        schema=GeneratedHooks,
        default=GeneratedHooks,
        blank=True,
        help_text=_("Agent-generated hook variations for the video opening."),
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
    qa_issues_found = PydanticField(
        schema=QAIssueList,
        default=QAIssueList,
        blank=True,
        help_text=_("QA issues found in the script."),
    )
    qa_issues_fixed = PydanticField(
        schema=QAIssueList,
        default=QAIssueList,
        blank=True,
        help_text=_("QA issues that have been resolved."),
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
    chapters = PydanticField(
        schema=ChapterList,
        default=ChapterList,
        help_text=_("YouTube chapter markers for the video."),
    )
    pinned_comment = models.TextField(
        blank=True,
        help_text=_("Comment to pin on video"),
    )

    # B-roll suggestions (structured for AssetJob)
    broll_suggestions = PydanticField(
        schema=BRollSuggestions,
        default=BRollSuggestions,
        blank=True,
        help_text=_("B-roll cues consumed by AssetJob for image generation."),
    )

    # TTS segments (pre-chunked for parallel generation)
    segments = PydanticField(
        schema=SegmentList,
        default=SegmentList,
        blank=True,
        help_text=_("Pre-chunked TTS segments driving VoiceoverSegment creation."),
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
        hooks = self.generated_hooks.root if self.generated_hooks else []
        if hooks and len(hooks) > self.selected_hook_idx:
            return hooks[self.selected_hook_idx]
        return None

    @property
    def revision_count(self) -> int:
        """Count of script revisions."""
        return self.revisions.count()

    @property
    def total_segments(self) -> int:
        """Count of TTS segments."""
        return len(self.segments.root) if self.segments else 0

    @property
    def broll_count(self) -> int:
        """Count of B-roll suggestions."""
        return len(self.broll_suggestions.root) if self.broll_suggestions else 0


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
