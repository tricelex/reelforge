"""Admin registrations for the ideas app."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
    RangeNumericFilter,
)

from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.models import TopicIdea
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_header_method,
)

_IDEA_STATUS_COLORS = {
    **STANDARD_STATUS_COLORS,
    IdeaStatus.BACKLOG: 'info',
    IdeaStatus.APPROVED: 'success',
}


@admin.register(TopicIdea)
class TopicIdeaAdmin(ReelForgeAdmin):
    """Admin for topic backlog items."""

    list_display = (
        'display_title',
        'channel',
        'display_status',
        'score',
        'created_at',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
        ('score', RangeNumericFilter),
    )
    search_fields = ('title', 'topic')
    autocomplete_fields = ('channel', 'niche', 'run')
    readonly_fields = ('metadata', 'created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'channel',
                    'niche',
                    'title',
                    'topic',
                    'score',
                    'status',
                    'run',
                    'rejection_reason',
                ),
            },
        ),
        (
            _('Metadata'),
            {
                'classes': ('tab',),
                'fields': ('metadata', 'created_at', 'updated_at'),
            },
        ),
    )

    display_title = make_header_method(
        'display_title',
        _('Idea'),
        lambda obj: obj.title[:60],
        lambda obj: obj.topic[:80],
    )
    display_status = make_badge_method(
        'status',
        _IDEA_STATUS_COLORS,
        description=_('Status'),
    )
