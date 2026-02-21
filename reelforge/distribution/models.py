from __future__ import annotations

from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from ***REMOVED***.core.fields import PydanticField
from ***REMOVED***.core.models import BaseAbstractModel
from ***REMOVED***.core.models import PipelineStageModel
from ***REMOVED***.distribution.choices import PerformanceClass
from ***REMOVED***.distribution.choices import UploadStatus
from ***REMOVED***.distribution.choices import YouTubePrivacy
from ***REMOVED***.distribution.schemas import AIInsights
from ***REMOVED***.distribution.schemas import TrafficSourceData

# Performance classification thresholds
VIRAL_THRESHOLD = 100_000  # 100k+ views in 7 days
ABOVE_AVG_THRESHOLD = 10_000  # 10k+ views in 7 days
AVERAGE_THRESHOLD = 1_000  # 1k+ views in 7 days


class DistributionJob(PipelineStageModel):
    """YouTube upload, scheduling, and cross-posting.
    Final stage of the pipeline.
    """

    production_job = models.OneToOneField(
        "production.ProductionJob",
        on_delete=models.CASCADE,
        related_name="distribution_job",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="distribution_jobs",
    )

    # YouTube upload
    youtube_video_id = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
    )
    youtube_video_url = models.URLField(blank=True)
    youtube_upload_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING,
    )
    privacy_status = models.CharField(
        max_length=10,
        choices=YouTubePrivacy.choices,
        default=YouTubePrivacy.PUBLIC,
    )

    # Metadata
    published_title = models.CharField(max_length=100)
    published_description = models.TextField()
    published_tags = ArrayField(
        models.CharField(max_length=100),
        default=list,
    )

    # Scheduling
    scheduled_publish_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("If not null, video is scheduled for future publish"),
    )
    published_at = models.DateTimeField(null=True, blank=True)

    # Playlist assignment
    playlist_ids = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text=_("YouTube playlist IDs this video was added to"),
    )

    # Shorts (YouTube Shorts)
    shorts_uploaded = models.BooleanField(default=False)
    shorts_youtube_id = models.CharField(max_length=50, blank=True)
    shorts_youtube_url = models.URLField(blank=True)
    shorts_upload_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING,
    )

    # Cross-posting (other platforms)
    tiktok_post_id = models.CharField(max_length=100, blank=True)
    tiktok_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING,
    )
    instagram_post_id = models.CharField(max_length=100, blank=True)
    instagram_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING,
    )
    twitter_post_id = models.CharField(max_length=100, blank=True)
    twitter_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING,
    )

    # Engagement setup
    cards_set = models.BooleanField(
        default=False,
        help_text=_("Whether YouTube cards have been added"),
    )
    pinned_comment_text = models.TextField(blank=True)
    pinned_comment_id = models.CharField(max_length=100, blank=True)
    chapters_added = models.BooleanField(default=False)

    # Performance tracking
    views_24h = models.PositiveIntegerField(default=0)
    views_7d = models.PositiveIntegerField(default=0)
    views_30d = models.PositiveIntegerField(default=0)
    ctr_percent = models.FloatField(
        default=0.0,
        help_text=_("Click-through rate from impressions"),
    )
    avg_view_duration_seconds = models.FloatField(default=0.0)
    avg_view_percentage = models.FloatField(
        default=0.0,
        help_text=_("Average percentage of video watched"),
    )
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    class Meta:
        ordering = ["-published_at"]
        verbose_name = _("Distribution Job")
        verbose_name_plural = _("Distribution Jobs")
        indexes = [
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["channel", "published_at"]),
            models.Index(fields=["youtube_video_id"]),
            models.Index(fields=["production_job"]),
        ]

    def __str__(self) -> str:
        return f"Distribution: {self.published_title[:60]}"

    @property
    def performance_class(self) -> str:
        if self.views_7d >= VIRAL_THRESHOLD:
            return PerformanceClass.VIRAL
        # Simple heuristic - can be improved with channel averages
        if self.views_7d >= ABOVE_AVG_THRESHOLD:
            return PerformanceClass.ABOVE_AVG
        if self.views_7d >= AVERAGE_THRESHOLD:
            return PerformanceClass.AVERAGE
        return PerformanceClass.UNDERPERFORM


class AnalyticsSnapshot(BaseAbstractModel):
    """Periodic analytics snapshots for a video.
    Polled at 1d, 7d, 30d intervals.
    """

    distribution_job = models.ForeignKey(
        DistributionJob,
        on_delete=models.CASCADE,
        related_name="analytics_snapshots",
    )
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="analytics_snapshots",
        help_text=_("Channel for aggregated analytics"),
    )

    snapshot_days_after = models.PositiveIntegerField(
        help_text=_("Days since publish when this snapshot was taken (1, 7, 30)"),
    )

    # Core metrics
    views = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    subscribers_gained = models.IntegerField(default=0)
    watch_time_hrs = models.FloatField(
        default=0.0,
        help_text=_("Total watch time in hours"),
    )

    # Engagement metrics
    impressions = models.PositiveIntegerField(default=0)
    ctr_percent = models.FloatField(default=0.0)
    avg_view_duration_seconds = models.FloatField(default=0.0)
    avg_view_percentage = models.FloatField(default=0.0)

    # Traffic sources
    traffic_source_data = PydanticField(
        schema=TrafficSourceData,
        default=TrafficSourceData,
        help_text=_("YouTube Analytics traffic source breakdown: source_name → percentage."),
    )

    # Revenue
    revenue_est_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    rpm_usd = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text=_("Revenue per 1000 views"),
    )

    # Performance classification
    performance_class = models.CharField(
        max_length=20,
        choices=PerformanceClass.choices,
        default=PerformanceClass.UNDERPERFORM,
        help_text=_("Performance classification based on views and engagement"),
    )

    # AI insights for feedback loop
    ai_insights = PydanticField(
        schema=AIInsights,
        default=AIInsights,
        blank=True,
        help_text=_("AI-generated performance analysis for the research feedback loop."),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Analytics Snapshot")
        verbose_name_plural = _("Analytics Snapshots")
        unique_together = [["distribution_job", "snapshot_days_after"]]
        indexes = [
            models.Index(fields=["distribution_job", "snapshot_days_after"]),
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.snapshot_days_after}d snapshot: {self.views} views"
