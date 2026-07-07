"""Django admin registrations for the clips app."""

from typing import ClassVar

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
    RangeDateFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
)

from server.apps.clips.logic.constants import (
    CampaignStatus,
    CandidateStatus,
    ClipSourceStatus,
    PostStatus,
)
from server.apps.clips.models import (
    ClipCampaign,
    ClipCandidate,
    ClipLayoutConfig,
    ClipPost,
    ClipSource,
    ClipStyleConfig,
    ClipTimedOverlay,
    ClipTimedSfx,
    Earning,
)
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_header_method,
    make_money_method,
)

_CLIP_STATUS_COLORS = {
    **STANDARD_STATUS_COLORS,
    CandidateStatus.PROPOSED: 'info',
    CandidateStatus.APPROVED: 'success',
    CandidateStatus.RENDERING: 'info',
    CandidateStatus.RENDERED: 'success',
    CandidateStatus.DISTRIBUTING: 'info',
    CandidateStatus.DISTRIBUTED: 'success',
    PostStatus.PENDING: 'info',
    PostStatus.POSTING: 'info',
    PostStatus.POSTED: 'success',
    CampaignStatus.DRAFT: 'info',
    CampaignStatus.ACTIVE: 'success',
    ClipSourceStatus.INGESTING: 'info',
    ClipSourceStatus.READY: 'success',
}


class ClipLayoutConfigInline(TabularInline):  # type: ignore[misc]
    """Inline for layout config on a ClipCandidate."""

    model = ClipLayoutConfig
    extra = 0
    tab = True
    fields = ('render_mode', 'render_format', 'stack_ratio', 'face_detected')


class ClipStyleConfigInline(TabularInline):  # type: ignore[misc]
    """Inline for style config on a ClipCandidate."""

    model = ClipStyleConfig
    extra = 0
    tab = True
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
    tab = True
    fields = ('overlay_type', 'text', 'start_sec', 'end_sec', 'opacity')


class ClipTimedSfxInline(TabularInline):  # type: ignore[misc]
    """Inline for timed sound effects on a ClipCandidate."""

    model = ClipTimedSfx
    extra = 0
    tab = True
    fields = ('sfx_asset', 'start_sec', 'volume_db')
    autocomplete_fields = ('sfx_asset',)


class ClipPostInline(TabularInline):  # type: ignore[misc]
    """Inline for posts on a ClipCandidate."""

    model = ClipPost
    extra = 0
    tab = True
    fields = ('platform', 'status', 'scheduled_at', 'posted_at')


@admin.register(ClipCandidate)
class ClipCandidateAdmin(ReelForgeAdmin):
    """Admin for ClipCandidate."""

    list_display = (
        'display_title',
        'display_status',
        'relevance_score',
        'start_sec',
        'end_sec',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('is_manual', ChoicesCheckboxFilter),
        ('run', AutocompleteSelectFilter),
        ('relevance_score', RangeNumericFilter),
    )
    search_fields = ('title', 'hook_text', 'run__topic')
    autocomplete_fields = ('run',)
    list_select_related = ('run',)
    readonly_fields = (
        'render_asset_id',
        'preview_asset_id',
        'created_at',
        'updated_at',
    )
    inlines: ClassVar = [
        ClipLayoutConfigInline,
        ClipStyleConfigInline,
        ClipTimedOverlayInline,
        ClipTimedSfxInline,
        ClipPostInline,
    ]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'run',
                    'title',
                    'status',
                    'relevance_score',
                    'is_manual',
                    'start_sec',
                    'end_sec',
                    'hook_text',
                    'render_asset_id',
                    'preview_asset_id',
                ),
            },
        ),
        (
            _('Transcript'),
            {
                'classes': ('tab',),
                'fields': (
                    'transcript_excerpt',
                    'caption_template',
                    'reason',
                    'rejection_reason',
                ),
            },
        ),
    )

    display_title = make_header_method(
        'display_title',
        _('Clip'),
        lambda obj: obj.title[:60],
        lambda obj: str(obj.run),
    )
    display_status = make_badge_method(
        'status',
        _CLIP_STATUS_COLORS,
        description=_('Status'),
    )


@admin.register(ClipLayoutConfig)
class ClipLayoutConfigAdmin(ReelForgeAdmin):
    """Admin for ClipLayoutConfig."""

    list_display = ('candidate', 'render_mode', 'render_format', 'stack_ratio')
    list_filter = (
        ('render_mode', ChoicesCheckboxFilter),
        ('render_format', ChoicesCheckboxFilter),
    )
    autocomplete_fields = ('candidate',)


@admin.register(ClipStyleConfig)
class ClipStyleConfigAdmin(ReelForgeAdmin):
    """Admin for ClipStyleConfig — full render style configuration."""

    list_display = (
        'candidate',
        'caption_enabled',
        'caption_style',
        'hook_enabled',
        'watermark_enabled',
        'music_enabled',
    )
    list_filter = (
        ('caption_style', ChoicesCheckboxFilter),
        ('caption_position', ChoicesCheckboxFilter),
        ('hook_style', ChoicesCheckboxFilter),
        ('watermark_enabled', ChoicesCheckboxFilter),
        ('music_enabled', ChoicesCheckboxFilter),
        ('color_filter', ChoicesCheckboxFilter),
    )
    search_fields = ('candidate__title',)
    autocomplete_fields = (
        'candidate',
        'caption_font_asset',
        'hook_font_asset',
        'intro_transition_asset',
        'outro_transition_asset',
        'intro_asset',
        'outro_asset',
        'watermark_image',
        'watermark_font_asset',
        'music_asset',
        'lut_asset',
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': ('candidate', 'created_at', 'updated_at'),
            },
        ),
        (
            _('Captions'),
            {
                'classes': ('tab',),
                'fields': (
                    'caption_enabled',
                    'caption_style',
                    'caption_font',
                    'caption_font_asset',
                    'caption_size',
                    'caption_color',
                    'caption_stroke_color',
                    'caption_stroke_width',
                    'caption_bg_color',
                    'caption_highlight_color',
                    'caption_position',
                    'caption_animation',
                    'caption_uppercase',
                    'caption_language',
                    'caption_translate_to',
                    'emoji_keyword_map',
                ),
            },
        ),
        (
            _('Hook'),
            {
                'classes': ('tab',),
                'fields': (
                    'hook_enabled',
                    'hook_style',
                    'hook_font',
                    'hook_font_asset',
                    'hook_size',
                    'hook_color',
                    'hook_bg_color',
                    'hook_duration_sec',
                    'hook_animation',
                ),
            },
        ),
        (
            _('Transitions & bumpers'),
            {
                'classes': ('tab',),
                'fields': (
                    'intro_transition',
                    'intro_transition_duration_sec',
                    'intro_transition_asset',
                    'outro_transition',
                    'outro_transition_duration_sec',
                    'outro_transition_asset',
                    'intro_asset',
                    'outro_asset',
                ),
            },
        ),
        (
            _('Watermark'),
            {
                'classes': ('tab',),
                'fields': (
                    'watermark_enabled',
                    'watermark_type',
                    'watermark_text',
                    'watermark_image',
                    'watermark_position',
                    'watermark_opacity',
                    'watermark_size',
                    'watermark_color',
                    'watermark_font',
                    'watermark_font_asset',
                ),
            },
        ),
        (
            _('Progress bar'),
            {
                'classes': ('tab',),
                'fields': (
                    'progress_bar_enabled',
                    'progress_bar_position',
                    'progress_bar_color',
                    'progress_bar_height',
                ),
            },
        ),
        (
            _('Music'),
            {
                'classes': ('tab',),
                'fields': (
                    'music_enabled',
                    'music_asset',
                    'music_volume_db',
                    'music_fade_in_sec',
                    'music_fade_out_sec',
                ),
            },
        ),
        (
            _('Color grade'),
            {
                'classes': ('tab',),
                'fields': (
                    'color_filter',
                    'brightness',
                    'contrast',
                    'saturation',
                    'lut_asset',
                    'playback_speed',
                ),
            },
        ),
    )


@admin.register(ClipTimedOverlay)
class ClipTimedOverlayAdmin(ReelForgeAdmin):
    """Admin for ClipTimedOverlay."""

    list_display = ('candidate', 'overlay_type', 'text', 'start_sec', 'end_sec')
    list_filter = (
        ('overlay_type', ChoicesCheckboxFilter),
        ('shape', ChoicesCheckboxFilter),
        ('animation', ChoicesCheckboxFilter),
    )
    search_fields = ('text', 'candidate__title')
    autocomplete_fields = (
        'candidate',
        'image_asset',
        'video_asset',
        'font_asset',
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'candidate',
                    'overlay_type',
                    'text',
                    'shape',
                    'start_sec',
                    'end_sec',
                    'x',
                    'y',
                    'width',
                    'opacity',
                    'animation',
                ),
            },
        ),
        (
            _('Text style'),
            {
                'classes': ('tab',),
                'fields': ('font', 'font_asset', 'font_size', 'color'),
            },
        ),
        (
            _('Media'),
            {
                'classes': ('tab',),
                'fields': ('image_asset', 'video_asset'),
            },
        ),
        (
            _('Timestamps'),
            {
                'classes': ('tab',),
                'fields': ('created_at', 'updated_at'),
            },
        ),
    )


@admin.register(ClipTimedSfx)
class ClipTimedSfxAdmin(ReelForgeAdmin):
    """Admin for ClipTimedSfx."""

    list_display = ('candidate', 'sfx_asset', 'start_sec', 'volume_db')
    search_fields = ('candidate__title', 'sfx_asset__name')
    autocomplete_fields = ('candidate', 'sfx_asset')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ClipPost)
class ClipPostAdmin(ReelForgeAdmin):
    """Admin for ClipPost."""

    list_display = (
        'candidate',
        'platform',
        'display_status',
        'scheduled_at',
        'posted_at',
    )
    list_filter = (
        ('platform', ChoicesCheckboxFilter),
        ('status', ChoicesCheckboxFilter),
        ('scheduled_at', RangeDateTimeFilter),
    )
    search_fields = ('platform', 'platform_post_id', 'candidate__title')
    autocomplete_fields = ('candidate',)
    list_select_related = ('candidate',)
    readonly_fields = ('hashtags', 'created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'candidate',
                    'platform',
                    'status',
                    'caption',
                    'title',
                    'scheduled_at',
                    'posted_at',
                    'platform_post_id',
                    'platform_url',
                    'last_error',
                ),
            },
        ),
        (
            _('Hashtags'),
            {
                'classes': ('tab',),
                'fields': ('hashtags',),
            },
        ),
        (
            _('Metrics'),
            {
                'classes': ('tab',),
                'fields': (
                    'views',
                    'likes',
                    'comments',
                    'shares',
                    'revenue_est_usd',
                ),
            },
        ),
        (
            _('Timestamps'),
            {
                'classes': ('tab',),
                'fields': ('created_at', 'updated_at'),
            },
        ),
    )

    display_status = make_badge_method(
        'status',
        _CLIP_STATUS_COLORS,
        description=_('Status'),
    )


@admin.register(ClipCampaign)
class ClipCampaignAdmin(ReelForgeAdmin):
    """Admin for ClipCampaign."""

    list_display = ('name', 'channel', 'display_status', 'created_at')
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
    )
    search_fields = ('name',)
    autocomplete_fields = ('channel',)

    display_status = make_badge_method(
        'status',
        _CLIP_STATUS_COLORS,
        description=_('Status'),
    )


@admin.register(ClipSource)
class ClipSourceAdmin(ReelForgeAdmin):
    """Admin for ClipSource."""

    list_display = (
        'display_title',
        'channel',
        'source_type',
        'display_status',
        'duration_sec',
        'created_at',
    )
    list_filter = (
        ('source_type', ChoicesCheckboxFilter),
        ('status', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
    )
    search_fields = ('title', 'url')
    autocomplete_fields = ('channel',)
    readonly_fields = ('library_asset_id', 'created_at', 'updated_at')

    display_title = make_header_method(
        'display_title',
        _('Source'),
        lambda obj: obj.title[:60],
        lambda obj: obj.url[:80] if obj.url else None,
    )
    display_status = make_badge_method(
        'status',
        _CLIP_STATUS_COLORS,
        description=_('Status'),
    )


@admin.register(Earning)
class EarningAdmin(ReelForgeAdmin):
    """Admin for Earning."""

    list_display = (
        'campaign',
        'platform',
        'display_revenue_est_usd',
        'recorded_at',
    )
    list_filter = (
        ('platform', ChoicesCheckboxFilter),
        ('revenue_est_usd', RangeNumericFilter),
        ('recorded_at', RangeDateFilter),
    )
    autocomplete_fields = ('campaign',)

    display_revenue_est_usd = make_money_method(
        'revenue_est_usd',
        description=_('Revenue'),
    )
