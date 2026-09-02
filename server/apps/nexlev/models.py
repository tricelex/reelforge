"""Persistent NexLev records: per-channel, per-video, and search cache."""

from typing import override

from django.db import models


class NexLevChannelRecord(models.Model):
    """One row per NexLev channel_id; each section tracks its own fetch."""

    channel_id = models.CharField(max_length=64, unique=True, db_index=True)

    about = models.JSONField(null=True, blank=True)
    about_fetched_at = models.DateTimeField(null=True, blank=True)

    outliers = models.JSONField(null=True, blank=True)
    outliers_fetched_at = models.DateTimeField(null=True, blank=True)

    analytics = models.JSONField(null=True, blank=True)
    analytics_fetched_at = models.DateTimeField(null=True, blank=True)

    similar_channels = models.JSONField(null=True, blank=True)
    similar_channels_fetched_at = models.DateTimeField(null=True, blank=True)

    niche_overview = models.JSONField(null=True, blank=True)
    niche_overview_fetched_at = models.DateTimeField(null=True, blank=True)

    channel_analysis = models.JSONField(null=True, blank=True)
    channel_analysis_fetched_at = models.DateTimeField(null=True, blank=True)

    quota_spent = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for NexLevChannelRecord."""

        verbose_name = 'NexLev channel record'

    @override
    def __str__(self) -> str:
        return self.channel_id


class NexLevVideoRecord(models.Model):
    """One row per NexLev video_id; content is effectively immutable."""

    video_id = models.CharField(max_length=32, unique=True, db_index=True)

    details = models.JSONField(null=True, blank=True)
    details_fetched_at = models.DateTimeField(null=True, blank=True)

    transcript = models.JSONField(null=True, blank=True)
    transcript_fetched_at = models.DateTimeField(null=True, blank=True)

    comments = models.JSONField(null=True, blank=True)
    comments_fetched_at = models.DateTimeField(null=True, blank=True)

    quota_spent = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for NexLevVideoRecord."""

        verbose_name = 'NexLev video record'

    @override
    def __str__(self) -> str:
        return self.video_id


class NexLevSearchCacheEntry(models.Model):
    """Short-TTL blob cache for live `youtube/search` results only."""

    cache_key = models.CharField(max_length=64, unique=True, db_index=True)
    payload = models.JSONField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    quota_spent = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options for NexLevSearchCacheEntry."""

        verbose_name = 'NexLev search cache entry'

    @override
    def __str__(self) -> str:
        return self.cache_key
