"""Django admin registration for the publishing app."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
    RangeDateFilter,
)

from server.apps.publishing.models import PublishJob, PublishStatus
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
)

_PUBLISH_STATUS_COLORS = {
    **STANDARD_STATUS_COLORS,
    PublishStatus.PENDING: 'info',
    PublishStatus.UPLOADING: 'info',
    PublishStatus.COMPLETED: 'success',
}


@admin.register(PublishJob)
class PublishJobAdmin(ReelForgeAdmin):
    """Admin panel for PublishJob."""

    list_display = (
        'id',
        'channel',
        'display_status',
        'youtube_video_id',
        'created_at',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
        ('created_at', RangeDateFilter),
    )
    search_fields = ('youtube_video_id', 'run__topic', 'channel__name')
    autocomplete_fields = ('run', 'channel')
    list_select_related = ('channel', 'run')
    readonly_fields = (
        'id',
        'metadata_snapshot',
        'error',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'run',
                    'channel',
                    'status',
                    'youtube_video_id',
                    'schedule_at',
                ),
            },
        ),
        (
            _('Metadata'),
            {
                'classes': ('tab',),
                'fields': ('metadata_snapshot',),
            },
        ),
        (
            _('Error'),
            {
                'classes': ('tab',),
                'fields': ('error',),
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
        _PUBLISH_STATUS_COLORS,
        description=_('Status'),
    )
