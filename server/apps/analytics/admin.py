"""Django admin registration for the analytics app.

RunCostSummary, ChannelRoi, and StagePerformance are read-only materialized
views (managed = False) and are intentionally not registered here — they have
no stable primary key semantics for admin editing and are better surfaced via
the analytics dashboard API. PublishJobMetric is a real table (populated by
the daily pull_publish_job_metrics task) and is registered read-only below.
"""

from typing import ClassVar

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
)

from server.apps.analytics.models import PublishJobMetric
from server.common.admin import ReelForgeAdmin


@admin.register(PublishJobMetric)
class PublishJobMetricAdmin(ReelForgeAdmin):
    """Admin panel for YouTube performance snapshots (read-only)."""

    list_display = (
        'publish_job',
        'views',
        'avg_view_percentage',
        'impressions_ctr',
        'pulled_at',
    )
    list_filter = (
        ('publish_job__channel', AutocompleteSelectFilter),
        ('views', RangeNumericFilter),
        ('pulled_at', RangeDateTimeFilter),
    )
    search_fields = (
        'publish_job__youtube_video_id',
        'publish_job__channel__name',
    )
    autocomplete_fields = ('publish_job',)
    list_select_related: ClassVar = ('publish_job', 'publish_job__channel')
    readonly_fields = (
        'publish_job',
        'pulled_at',
        'views',
        'avg_view_duration_s',
        'avg_view_percentage',
        'impressions',
        'impressions_ctr',
        'retention_curve',
    )
    fieldsets = (
        (
            None,
            {
                'fields': ('publish_job', 'pulled_at'),
            },
        ),
        (
            _('Metrics'),
            {
                'classes': ('tab',),
                'fields': (
                    'views',
                    'avg_view_duration_s',
                    'avg_view_percentage',
                    'impressions',
                    'impressions_ctr',
                ),
            },
        ),
        (
            _('Retention curve'),
            {
                'classes': ('tab',),
                'fields': ('retention_curve',),
            },
        ),
    )

    def has_add_permission(self, request: object) -> bool:
        """Metrics are pulled by the daily analytics task only."""
        return False

    def has_change_permission(
        self,
        request: object,
        obj: PublishJobMetric | None = None,
    ) -> bool:
        """Metric snapshots are immutable."""
        return False
