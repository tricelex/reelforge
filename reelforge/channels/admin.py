from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import display

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import ChannelCompetitor
from ***REMOVED***.channels.models import ChannelPlaylist


class ChannelCompetitorInline(TabularInline):
    model = ChannelCompetitor
    extra = 0
    fields = [
        "youtube_channel_id",
        "channel_name",
        "channel_url",
        "subscriber_count",
        "last_analyzed",
    ]
    readonly_fields = ["last_analyzed"]


class ChannelPlaylistInline(TabularInline):
    model = ChannelPlaylist
    extra = 0
    fields = [
        "name",
        "youtube_playlist_id",
        "niche_tag",
        "auto_assign",
        "video_count",
    ]
    readonly_fields = ["video_count"]


@admin.register(Channel)
class ChannelAdmin(ModelAdmin):
    list_display = [
        "id",
        "name",
        "slug",
        "status_badge",
        "niche_category",
        "youtube_handle",
        "total_videos_published",
        "total_views",
        "total_subscribers",
        "created_at",
    ]
    list_filter = [
        "status",
        "niche_category",
        "monetization_enabled",
        "auto_approve_scripts",
        "auto_upload",
        "created_at",
    ]
    search_fields = [
        "name",
        "slug",
        "youtube_handle",
        "youtube_channel_id",
        "description",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "total_videos_published",
        "total_views",
        "total_subscribers",
        "total_revenue_est_usd",
        "last_analytics_sync",
        "active_niche",
    ]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ChannelCompetitorInline, ChannelPlaylistInline]

    fieldsets = (
        (
            _("Basic Information"),
            {
                "fields": (
                    "id",
                    "name",
                    "slug",
                    "description",
                    "status",
                ),
            },
        ),
        (
            _("YouTube Credentials & IDs"),
            {
                "fields": (
                    "youtube_channel_id",
                    "youtube_handle",
                    "oauth_credentials",
                    "analytics_property",
                ),
            },
        ),
        (
            _("Niche Configuration"),
            {
                "fields": (
                    "niche_category",
                    "custom_niche",
                    "active_niche",
                    "target_niches",
                ),
            },
        ),
        (
            _("Target Audience"),
            {
                "classes": ("collapse",),
                "fields": (
                    "target_audience_description",
                    "target_age_range",
                    "target_location",
                ),
            },
        ),
        (
            _("Content Configuration"),
            {
                "fields": (
                    "content_tone",
                    "video_length_min",
                    "video_length_max",
                    "upload_frequency",
                    "upload_schedule",
                ),
            },
        ),
        (
            _("Branding"),
            {
                "classes": ("collapse",),
                "fields": (
                    "logo_file",
                    "brand_color_hex",
                    "brand_color_secondary",
                    "font_primary",
                    "channel_intro_file",
                    "channel_outro_file",
                    "default_thumbnail_template",
                ),
            },
        ),
        (
            _("Voice Configuration"),
            {
                "fields": (
                    "tts_provider",
                    "tts_voice_id",
                    "tts_voice_name",
                    "tts_stability",
                    "tts_similarity",
                    "tts_style",
                ),
            },
        ),
        (
            _("Music Preferences"),
            {
                "classes": ("collapse",),
                "fields": (
                    "music_style",
                    "music_volume_pct",
                ),
            },
        ),
        (
            _("SEO & Monetization"),
            {
                "classes": ("collapse",),
                "fields": (
                    "default_tags",
                    "channel_keywords",
                    "monetization_enabled",
                    "estimated_rpm_usd",
                ),
            },
        ),
        (
            _("API Provider Preferences"),
            {
                "classes": ("collapse",),
                "fields": (
                    "llm_provider",
                    "image_provider",
                    "video_provider",
                ),
            },
        ),
        (
            _("Pipeline Automation Config"),
            {
                "fields": (
                    "auto_approve_scripts",
                    "auto_approve_assets",
                    "auto_upload",
                    "auto_approve_delay_hrs",
                ),
            },
        ),
        (
            _("Boilerplate"),
            {
                "classes": ("collapse",),
                "fields": (
                    "description_boilerplate",
                    "default_pinned_comment_template",
                ),
            },
        ),
        (
            _("Stats"),
            {
                "fields": (
                    "total_videos_published",
                    "total_views",
                    "total_subscribers",
                    "total_revenue_est_usd",
                    "last_analytics_sync",
                ),
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

    @display(
        description=_("Status"),
        ordering="status",
        label={
            "ACTIVE": "success",
            "PAUSED": "warning",
            "ARCHIVED": "default",
            "SETUP": "info",
        },
    )
    def status_badge(self, obj: Channel) -> str:
        return obj.status


@admin.register(ChannelCompetitor)
class ChannelCompetitorAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel",
        "channel_name",
        "subscriber_count",
        "last_analyzed",
    ]
    list_filter = ["channel", "last_analyzed"]
    search_fields = [
        "id",
        "channel_name",
        "youtube_channel_id",
        "channel__name",
    ]
    readonly_fields = ["id", "created_at", "updated_at", "last_analyzed"]
    autocomplete_fields = ["channel"]


@admin.register(ChannelPlaylist)
class ChannelPlaylistAdmin(ModelAdmin):
    list_display = [
        "id",
        "channel",
        "name",
        "niche_tag",
        "auto_assign",
        "video_count",
    ]
    list_filter = ["channel", "auto_assign"]
    search_fields = [
        "id",
        "name",
        "niche_tag",
        "youtube_playlist_id",
        "channel__name",
    ]
    readonly_fields = ["id", "created_at", "updated_at", "video_count"]
    autocomplete_fields = ["channel"]
