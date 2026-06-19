"""Django admin registrations for the clips app."""

from typing import ClassVar

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.clips.models import (
    ClipCampaign,
    ClipCandidate,
    ClipLayoutConfig,
    ClipPost,
    ClipStyleConfig,
    ClipTimedOverlay,
    Earning,
)


class ClipLayoutConfigInline(TabularInline):  # type: ignore[misc]
    """Inline for layout config on a ClipCandidate."""

    model = ClipLayoutConfig
    extra = 0
    fields = ('render_mode', 'render_format', 'stack_ratio', 'face_detected')


class ClipStyleConfigInline(TabularInline):  # type: ignore[misc]
    """Inline for style config on a ClipCandidate."""

    model = ClipStyleConfig
    extra = 0
    fields = (
        'caption_enabled',
        'caption_style',
        'hook_enabled',
        'watermark_enabled',
        'music_enabled',
    )


class ClipTimedOverlayInline(TabularInline):  # type: ignore[misc]
    """Inline for timed overlays on a ClipCandidate."""

    model = ClipTimedOverlay
    extra = 0
    fields = ('overlay_type', 'text', 'start_sec', 'end_sec', 'opacity')


class ClipPostInline(TabularInline):  # type: ignore[misc]
    """Inline for posts on a ClipCandidate."""

    model = ClipPost
    extra = 0
    fields = ('platform', 'status', 'scheduled_at', 'posted_at')


@admin.register(ClipCandidate)
class ClipCandidateAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipCandidate."""

    list_display = (
        'title',
        'run',
        'status',
        'relevance_score',
        'start_sec',
        'end_sec',
    )
    list_filter = ('status', 'is_manual')
    search_fields = ('title', 'hook_text', 'run__topic')
    readonly_fields = ('render_asset_id',)
    inlines: ClassVar = [
        ClipLayoutConfigInline,
        ClipStyleConfigInline,
        ClipTimedOverlayInline,
        ClipPostInline,
    ]


@admin.register(ClipLayoutConfig)
class ClipLayoutConfigAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipLayoutConfig."""

    list_display = ('candidate', 'render_mode', 'render_format', 'stack_ratio')
    list_filter = ('render_mode', 'render_format')


@admin.register(ClipStyleConfig)
class ClipStyleConfigAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipStyleConfig."""

    list_display = (
        'candidate',
        'caption_enabled',
        'caption_style',
        'hook_enabled',
        'watermark_enabled',
    )
    list_filter = ('caption_style', 'hook_style', 'watermark_enabled')


@admin.register(ClipTimedOverlay)
class ClipTimedOverlayAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipTimedOverlay."""

    list_display = ('candidate', 'overlay_type', 'text', 'start_sec', 'end_sec')
    list_filter = ('overlay_type',)
    search_fields = ('text',)


@admin.register(ClipPost)
class ClipPostAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipPost."""

    list_display = (
        'candidate',
        'platform',
        'status',
        'scheduled_at',
        'posted_at',
    )
    list_filter = ('platform', 'status')
    search_fields = ('platform', 'platform_post_id')


@admin.register(ClipCampaign)
class ClipCampaignAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for ClipCampaign."""

    list_display = ('name', 'channel', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(Earning)
class EarningAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for Earning."""

    list_display = (
        'campaign',
        'platform',
        'revenue_est_usd',
        'recorded_at',
    )
    list_filter = ('platform',)
