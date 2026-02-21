from __future__ import annotations

from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from ***REMOVED***.core.fields import PydanticField
from ***REMOVED***.core.models import PipelineStageModel
from ***REMOVED***.research.choices import ApprovalSource
from ***REMOVED***.research.choices import CompetitionLevel
from ***REMOVED***.research.choices import ResearchTrigger
from ***REMOVED***.research.choices import TrendDirection
from ***REMOVED***.research.schemas import CompetitorDataRaw
from ***REMOVED***.research.schemas import GapAnalysisRaw
from ***REMOVED***.research.schemas import TrendDataRaw


class ResearchJob(PipelineStageModel):
    """A research job that discovers trending topics for a channel.
    Runs periodically or manually triggered.
    Produces multiple TopicIdea candidates.
    """

    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="research_jobs",
    )

    # Trigger context
    trigger_source = models.CharField(
        max_length=20,
        choices=ResearchTrigger.choices,
        default=ResearchTrigger.SCHEDULED,
    )
    search_keywords = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text=_("Keywords used for this research run"),
    )
    competitor_channels_analyzed = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text=_("YouTube channel IDs analyzed"),
    )

    # Raw research data (for debugging, re-processing, audit)
    trend_data_raw = PydanticField(
        schema=TrendDataRaw,
        default=TrendDataRaw,
        blank=True,
        help_text=_("Raw data from Google Trends, YouTube search, etc."),
    )
    competitor_data_raw = PydanticField(
        schema=CompetitorDataRaw,
        default=CompetitorDataRaw,
        blank=True,
        help_text=_("Raw competitor channel analysis data"),
    )
    gap_analysis_raw = PydanticField(
        schema=GapAnalysisRaw,
        default=GapAnalysisRaw,
        blank=True,
        help_text=_("Raw gap detection and opportunity scoring data"),
    )

    # Results
    topics_discovered = models.PositiveSmallIntegerField(default=0)
    topics_approved = models.PositiveSmallIntegerField(default=0)
    topics_rejected = models.PositiveSmallIntegerField(default=0)

    # Research config snapshot
    min_search_volume = models.PositiveIntegerField(default=1000)
    max_competition = models.CharField(
        max_length=10,
        choices=CompetitionLevel.choices,
        default=CompetitionLevel.MEDIUM,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Research Job")
        verbose_name_plural = _("Research Jobs")
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
        ]

    def __str__(self) -> str:
        keywords = ", ".join(self.search_keywords[:3]) if self.search_keywords else "N/A"
        return f"Research: {self.channel.slug} - {keywords}"

    @property
    def approval_rate(self) -> float:
        if self.topics_discovered == 0:
            return 0.0
        return (self.topics_approved / self.topics_discovered) * 100


class TopicIdea(PipelineStageModel):
    """A single topic candidate from a research job.
    Can be approved → ScriptJob, or rejected.
    """

    research_job = models.ForeignKey(
        ResearchJob,
        on_delete=models.CASCADE,
        related_name="topics",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="topic_ideas",
    )

    # Topic content
    title_idea = models.CharField(max_length=255)
    description = models.TextField()
    angle = models.TextField(
        blank=True,
        help_text=_("Unique angle or hook for this topic"),
    )
    keywords = ArrayField(
        models.CharField(max_length=100),
        default=list,
    )

    # Research metrics
    estimated_search_volume = models.PositiveIntegerField(default=0)
    competition_level = models.CharField(
        max_length=10,
        choices=CompetitionLevel.choices,
        default=CompetitionLevel.MEDIUM,
    )
    trend_direction = models.CharField(
        max_length=10,
        choices=TrendDirection.choices,
        default=TrendDirection.STABLE,
    )
    trend_score = models.FloatField(
        default=0.0,
        help_text=_("0-10 trend score from agent"),
    )

    # Gap analysis
    competitor_video_count = models.PositiveSmallIntegerField(default=0)
    avg_competitor_views = models.PositiveIntegerField(default=0)
    gap_opportunity_score = models.FloatField(
        default=0.0,
        help_text=_("0-10 gap opportunity score"),
    )

    # Content hints from research
    thumbnail_concept = models.TextField(blank=True)
    why_it_works = models.TextField(blank=True)
    suggested_sources = ArrayField(models.URLField(), default=list)
    reddit_questions = ArrayField(models.TextField(), default=list)

    # Approval
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_topics",
    )
    approval_source = models.CharField(
        max_length=10,
        choices=ApprovalSource.choices,
        default=ApprovalSource.MANUAL,
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-trend_score", "-gap_opportunity_score"]
        verbose_name = _("Topic Idea")
        verbose_name_plural = _("Topic Ideas")
        indexes = [
            models.Index(fields=["status", "approved"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["research_job", "approved"]),
        ]

    def __str__(self) -> str:
        return f"Topic: {self.title_idea[:60]} [{self.channel.slug}]"

    @property
    def combined_score(self) -> float:
        """Combined trend + gap score for ranking."""
        return (self.trend_score + self.gap_opportunity_score) / 2
