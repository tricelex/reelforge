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
    readonly_fields = ('render_asset_id', 'created_at', 'updated_at')
    inlines: ClassVar = [
        ClipLayoutConfigInline,
        ClipStyleConfigInline,
        ClipTimedOverlayInline,
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
    """Admin for ClipStyleConfig."""

    list_display = (
        'candidate',
        'caption_enabled',
        'caption_style',
        'hook_enabled',
        'watermark_enabled',
    )
    list_filter = (
        ('caption_style', ChoicesCheckboxFilter),
        ('hook_style', ChoicesCheckboxFilter),
        ('watermark_enabled', ChoicesCheckboxFilter),
    )
    autocomplete_fields = ('candidate',)
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'candidate',
                    'caption_enabled',
                    'caption_style',
                    'hook_enabled',
                    'hook_style',
                    'watermark_enabled',
                    'music_enabled',
                ),
            },
        ),
        (
            _('Emoji map'),
            {
                'classes': ('tab',),
                'fields': ('emoji_keyword_map',),
            },
        ),
    )


@admin.register(ClipTimedOverlay)
class ClipTimedOverlayAdmin(ReelForgeAdmin):
    """Admin for ClipTimedOverlay."""

    list_display = ('candidate', 'overlay_type', 'text', 'start_sec', 'end_sec')
    list_filter = (('overlay_type', ChoicesCheckboxFilter),)
    search_fields = ('text',)
    autocomplete_fields = ('candidate',)


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
    search_fields = ('platform', 'platform_post_id')
    autocomplete_fields = ('candidate',)
    readonly_fields = ('hashtags',)
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
