from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline
from unfold.decorators import action
from unfold.decorators import display

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import ChannelCompetitor
from ***REMOVED***.channels.models import ChannelPlaylist
from ***REMOVED***.channels.services import ChannelSetupService

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse


class ChannelCompetitorInline(TabularInline):
    model = ChannelCompetitor
    extra = 0
    fields = [
        # "channel_name",
        "channel_url",
        "subscriber_count",
        "last_analyzed",
    ]
    readonly_fields = ["last_analyzed", "subscriber_count"]


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
        "name",
        "status_badge",
        "niche_category",
        "total_videos_published",
        "total_views_display",
        "total_revenue_display",
        "last_analytics_sync",
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
        "oauth_credentials_display",
    ]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ChannelCompetitorInline, ChannelPlaylistInline]
    actions_row = ["validate_voice", "setup_youtube_oauth"]
    actions = ["sync_analytics", "trigger_research"]

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
            _("YouTube"),
            {
                "fields": (
                    "youtube_channel_id",
                    "youtube_handle",
                    "oauth_credentials_display",
                    "analytics_property",
                ),
            },
        ),
        (
            _("Niche & Audience"),
            {
                "fields": (
                    "niche_category",
                    "custom_niche",
                    "active_niche",
                    "target_niches",
                    "target_audience_description",
                    "target_age_range",
                    "target_location",
                ),
            },
        ),
        (
            _("Content Settings"),
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
            _("Voice & Audio"),
            {
                "fields": (
                    "tts_provider",
                    "tts_voice_id",
                    "tts_voice_name",
                    "tts_stability",
                    "tts_similarity",
                    "tts_style",
                    "music_style",
                    "music_volume_pct",
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
            _("SEO"),
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
            _("Providers"),
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
            _("Automation"),
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

    @display(description="Total Views")
    def total_views_display(self, obj) -> str:
        return f"{obj.total_views:,}"

    @display(description="Revenue (Est.)")
    def total_revenue_display(self, obj) -> str:
        return f"${obj.total_revenue_est_usd:,.2f}"

    @display(
        description=_("OAuth Credentials"),
        label={
            "connected": "success",
            "not_configured": "default",
        },
    )
    def oauth_credentials_display(self, obj: Channel) -> tuple[str, str]:
        creds = obj.oauth_credentials
        if creds and creds.get("refresh_token"):
            preview = creds["refresh_token"][:12]
            return f"Connected ({preview}...)", "connected"
        return "Not configured", "not_configured"

    @action(description="🎙 Test Voice", url_path="validate-voice")
    def validate_voice(self, request: HttpRequest, object_id: int) -> HttpResponse:
        channel = Channel.objects.get(pk=object_id)
        if not channel.tts_voice_id:
            self.message_user(
                request,
                f"'{channel.name}' has no TTS voice ID configured.",
                level=messages.WARNING,
            )
            return redirect(reverse("admin:channels_channel_changelist"))

        svc = ChannelSetupService(channel)
        try:
            result = svc.validate_voice(voice_id=channel.tts_voice_id)
            self.message_user(
                request,
                f"Voice OK for '{channel.name}' — duration: {result['duration']:.1f}s, preview: {result['preview_path']}",
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Voice validation failed for '{channel.name}': {exc}",
                level=messages.ERROR,
            )
        return redirect(reverse("admin:channels_channel_changelist"))

    @action(description="🔑 Setup YouTube OAuth", url_path="setup-youtube-oauth")
    def setup_youtube_oauth(self, request: HttpRequest, object_id: int) -> HttpResponse:
        channel = Channel.objects.get(pk=object_id)
        redirect_uri: str = request.build_absolute_uri(reverse("youtube_oauth_callback"))

        svc = ChannelSetupService(channel)
        try:
            auth_url, state = svc.get_authorization_url(redirect_uri=redirect_uri)
        except Exception as exc:
            self.message_user(
                request,
                f"Failed to build OAuth URL for '{channel.name}': {exc}",
                level=messages.ERROR,
            )
            return redirect(reverse("admin:channels_channel_change", args=[object_id]))

        request.session["youtube_oauth_state"] = state
        request.session["youtube_oauth_channel_id"] = str(channel.id)

        return redirect(auth_url)

    @action(description="🚀 Trigger Research Job", url_path="trigger-research")
    def trigger_research(self, request, queryset) -> None:
        from ***REMOVED***.pipeline.tasks import run_research_job_for_channel

        for channel in queryset:
            run_research_job_for_channel.delay(str(channel.id))
        self.message_user(request, f"Research triggered for {queryset.count()} channels.")

    @action(description="📊 Sync Analytics Now", url_path="sync-analytics")
    def sync_analytics(self, request, queryset) -> None:
        from ***REMOVED***.pipeline.tasks import sync_channel_analytics

        for channel in queryset:
            sync_channel_analytics.delay(str(channel.id))
        self.message_user(request, "Analytics sync triggered.")


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
