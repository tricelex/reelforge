"""Admin registrations for channel research jobs."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
)

from server.apps.channel_research.logic.constants import ChannelResearchStatus
from server.apps.channel_research.models import ChannelResearchJob
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_header_method,
)

_STATUS_COLORS = {
    **STANDARD_STATUS_COLORS,
    ChannelResearchStatus.RUNNING: 'info',
}


@admin.register(ChannelResearchJob)
class ChannelResearchJobAdmin(ReelForgeAdmin):
    """Admin for channel research jobs."""

    list_display = (
        'display_title',
        'display_status',
        'kind',
        'created_by',
        'created_at',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('kind', ChoicesCheckboxFilter),
        ('created_by', AutocompleteSelectFilter),
    )
    search_fields = (
        'working_name',
        'source_channel_url',
        'source_channel_name',
    )
    autocomplete_fields = ('created_by',)
    readonly_fields = (
        'source_channel_id',
        'source_channel_name',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'source_channel_url',
                    'target_market',
                    'working_name',
                    'kind',
                    'notes',
                    'status',
                    'created_by',
                    'error_message',
                ),
            },
        ),
        (
            _('Resolved source'),
            {
                'classes': ('tab',),
                'fields': (
                    'source_channel_id',
                    'source_channel_name',
                ),
            },
        ),
        (
            _('Outputs'),
            {
                'classes': ('tab',),
                'fields': (
                    'research_report',
                    'channel_spec',
                    'tool_trace',
                    'usage',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )

    display_title = make_header_method(
        'display_title',
        _('Job'),
        lambda obj: (obj.working_name or obj.source_channel_url)[:60],
        lambda obj: obj.source_channel_name or obj.target_market,
    )
    display_status = make_badge_method(
        'status',
        _STATUS_COLORS,
        description=_('Status'),
    )
