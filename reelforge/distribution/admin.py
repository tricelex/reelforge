from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from ***REMOVED***.core.admin import FSMModelAdminMixin
from ***REMOVED***.distribution.models import AnalyticsSnapshot
from ***REMOVED***.distribution.models import DistributionJob


class AnalyticsSnapshotInline(TabularInline):
    model = AnalyticsSnapshot
    extra = 0
    fields = [
        "snapshot_days_after",
        "views",
        "watch_time_hrs",
        "ctr_percent",
        "avg_view_percentage",
        "performance_class",
        "revenue_est_usd",
        "created_at",
    ]
    readonly_fields = fields
    ordering = ["snapshot_days_after"]


@admin.register(DistributionJob)
class DistributionJobAdmin(FSMModelAdminMixin, ModelAdmin):
    list_display = [
        "id",
        "channel",
        "status_badge",
        "published_title",
        "youtube_link",
        "upload_status_badge",
        "privacy_status",
        "views_7d",
        "performance_class_display",
        "published_at",
    ]
    list_filter = [
        "status",
        "youtube_upload_status",
        "privacy_status",
        "shorts_uploaded",
        "shorts_upload_status",
        "tiktok_status",
        "instagram_status",
        "twitter_status",
        "published_at",
        "channel",
    ]
    search_fields = [
        "id",
        "published_title",
        "youtube_video_id",
        "channel__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "duration_seconds",
        "celery_task_id",
        "agent_run_id",
        "agent_tokens_used",
        "agent_cost_usd",
        "youtube_video_url",
        "shorts_youtube_url",
        "published_at",
        "performance_class",
    ]
    autocomplete_fields = ["channel", "production_job"]
    inlines = [AnalyticsSnapshotInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "channel",
                    "production_job",
                    "status",
                ),
            },
        ),
        (
            _("YouTube Upload"),
            {
                "fields": (
                    "youtube_video_id",
                    "youtube_video_url",
                    "youtube_upload_status",
                    "privacy_status",
                ),
            },
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "published_title",
                    "published_description",
                    "published_tags",
                ),
            },
        ),
        (
            _("Scheduling"),
            {
                "fields": (
                    "scheduled_publish_at",
                    "published_at",
                ),
            },
        ),
        (
            _("Playlist Assignment"),
            {
                "classes": ("collapse",),
                "fields": ("playlist_ids",),
            },
        ),
        (
            _("YouTube Shorts"),
            {
                "classes": ("collapse",),
                "fields": (
                    "shorts_uploaded",
                    "shorts_youtube_id",
                    "shorts_youtube_url",
                    "shorts_upload_status",
                ),
            },
        ),
        (
            _("Cross-Posting (Other Platforms)"),
            {
                "classes": ("collapse",),
                "fields": (
                    "tiktok_post_id",
                    "tiktok_status",
                    "instagram_post_id",
                    "instagram_status",
                    "twitter_post_id",
                    "twitter_status",
                ),
            },
        ),
        (
            _("Engagement Setup"),
            {
                "classes": ("collapse",),
                "fields": (
                    "pinned_comment_text",
                    "pinned_comment_id",
                    "chapters_added",
                    "cards_set",
                ),
            },
        ),
        (
            _("Performance Tracking"),
            {
                "fields": (
                    "views_24h",
                    "views_7d",
                    "views_30d",
                    "ctr_percent",
                    "avg_view_duration_seconds",
                    "avg_view_percentage",
                    "revenue_est_usd",
                    "performance_class",
                ),
            },
        ),
        (
            _("Agent Execution"),
            {
                "classes": ("collapse",),
                "fields": (
                    "agent_run_id",
                    "agent_tokens_used",
                    "agent_cost_usd",
                ),
            },
        ),
        (
            _("Timeline"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "started_at",
                    "completed_at",
                    "duration_seconds",
                ),
            },
        ),
        (
            _("Notes"),
            {
                "classes": ("collapse",),
                "fields": ("notes",),
            },
        ),
    )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            "PENDING": "default",
            "QUEUED": "info",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "RETRYING": "warning",
            "PAUSED": "warning",
            "REJECTED": "default",
            "SKIPPED": "default",
        },
    )
    def status_badge(self, obj: DistributionJob) -> str:
        return obj.status

    @display(
        description=_("Upload Status"),
        ordering="youtube_upload_status",
        label={
            "PENDING": "default",
            "UPLOADING": "info",
            "PROCESSING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def upload_status_badge(self, obj: DistributionJob) -> str:
        return obj.youtube_upload_status

    @display(description=_("YouTube Link"))
    def youtube_link(self, obj: DistributionJob) -> str:
        if obj.youtube_video_url:
            return format_html(
                '<a href="{}" target="_blank">Watch</a>',
                obj.youtube_video_url,
            )
        return "-"

    @display(
        description=_("Performance"),
        label={
            "VIRAL": "success",
            "ABOVE_AVG": "info",
            "AVERAGE": "default",
            "UNDERPERFORM": "warning",
        },
    )
    def performance_class_display(self, obj: DistributionJob) -> str:
        return obj.performance_class


@admin.register(AnalyticsSnapshot)
class AnalyticsSnapshotAdmin(ModelAdmin):
    list_display = [
        "id",
        "distribution_job",
        "channel",
        "snapshot_days_after",
        "views",
        "watch_time_hrs",
        "ctr_percent",
        "avg_view_percentage",
        "performance_class_display",
        "revenue_display",
        "created_at",
    ]
    list_filter = [
        "snapshot_days_after",
        "performance_class",
        "channel",
        "created_at",
    ]
    search_fields = [
        "id",
        "distribution_job__published_title",
        "distribution_job__youtube_video_id",
        "channel__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = ["distribution_job", "channel"]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "distribution_job",
                    "channel",
                    "snapshot_days_after",
                    "performance_class",
                ),
            },
        ),
        (
            _("Core Metrics"),
            {
                "fields": (
                    "views",
                    "watch_time_hrs",
                    "likes",
                    "comments",
                    "shares",
                    "subscribers_gained",
                ),
            },
        ),
        (
            _("Engagement Metrics"),
            {
                "fields": (
                    "impressions",
                    "ctr_percent",
                    "avg_view_duration_seconds",
                    "avg_view_percentage",
                ),
            },
        ),
        (
            _("Traffic Sources"),
            {
                "classes": ("collapse",),
                "fields": ("traffic_source_data",),
            },
        ),
        (
            _("Revenue"),
            {
                "fields": (
                    "revenue_est_usd",
                    "rpm_usd",
                ),
            },
        ),
        (
            _("AI Insights (Feedback Loop)"),
            {
                "classes": ("collapse",),
                "fields": ("ai_insights",),
            },
        ),
        (
            _("Timestamps"),
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @display(description=_("Revenue"), ordering="revenue_est_usd")
    def revenue_display(self, obj: AnalyticsSnapshot) -> str:
        return f"${obj.revenue_est_usd:.2f}"

    @display(
        description=_("Performance"),
        ordering="performance_class",
        label={
            "VIRAL": "success",
            "ABOVE_AVG": "info",
            "AVERAGE": "default",
            "UNDERPERFORM": "warning",
        },
    )
    def performance_class_display(self, obj: AnalyticsSnapshot) -> str:
        return obj.performance_class
