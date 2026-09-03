"""Django admin registrations for the nexlev app.

All three models are fetch-tracking/cache records populated by NexLev API
calls, not user-editable content, so every admin below is read-only.
"""

from django.contrib import admin

from server.apps.nexlev.models import (
    NexLevChannelRecord,
    NexLevSearchCacheEntry,
    NexLevVideoRecord,
)
from server.common.admin import ReelForgeAdmin


class _ReadOnlyAdmin(ReelForgeAdmin):
    """Base admin for records that are only ever written by background tasks."""

    def has_add_permission(self, request: object) -> bool:
        """Records are created by NexLev API calls only."""
        return False

    def has_change_permission(
        self,
        request: object,
        obj: object = None,
    ) -> bool:
        """Records are refreshed by NexLev API calls only."""
        return False


@admin.register(NexLevChannelRecord)
class NexLevChannelRecordAdmin(_ReadOnlyAdmin):
    """Admin panel for cached NexLev channel data."""

    list_display = (
        'channel_id',
        'quota_spent',
        'about_fetched_at',
        'analytics_fetched_at',
        'updated_at',
    )
    search_fields = ('channel_id',)
    readonly_fields = (
        'channel_id',
        'about',
        'about_fetched_at',
        'outliers',
        'outliers_fetched_at',
        'analytics',
        'analytics_fetched_at',
        'similar_channels',
        'similar_channels_fetched_at',
        'niche_overview',
        'niche_overview_fetched_at',
        'channel_analysis',
        'channel_analysis_fetched_at',
        'quota_spent',
        'created_at',
        'updated_at',
    )


@admin.register(NexLevVideoRecord)
class NexLevVideoRecordAdmin(_ReadOnlyAdmin):
    """Admin panel for cached NexLev video data."""

    list_display = (
        'video_id',
        'quota_spent',
        'details_fetched_at',
        'transcript_fetched_at',
        'updated_at',
    )
    search_fields = ('video_id',)
    readonly_fields = (
        'video_id',
        'details',
        'details_fetched_at',
        'transcript',
        'transcript_fetched_at',
        'comments',
        'comments_fetched_at',
        'quota_spent',
        'created_at',
        'updated_at',
    )


@admin.register(NexLevSearchCacheEntry)
class NexLevSearchCacheEntryAdmin(_ReadOnlyAdmin):
    """Admin panel for the short-TTL NexLev search cache."""

    list_display = ('cache_key', 'quota_spent', 'fetched_at')
    search_fields = ('cache_key',)
    readonly_fields = ('cache_key', 'payload', 'quota_spent', 'fetched_at')
