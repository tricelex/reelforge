"""Django admin registration for the prompts app."""

from typing import ClassVar

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import TabularInline
from unfold.contrib.filters.admin import ChoicesCheckboxFilter

from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import make_badge_method, make_boolean_badge_method


class PromptVersionInline(TabularInline):  # type: ignore[misc]
    """Inline editor for PromptVersion records."""

    model = PromptVersion
    extra = 0
    tab = True
    fields = ('version', 'model', 'is_active', 'temperature', 'max_tokens')


@admin.register(PromptTemplate)
class PromptTemplateAdmin(ReelForgeAdmin):
    """Admin panel for PromptTemplate."""

    list_display = ('key', 'name', 'display_scope')
    list_filter = (('scope', ChoicesCheckboxFilter),)
    search_fields = ('key', 'name')
    inlines: ClassVar = [PromptVersionInline]

    display_scope = make_badge_method(
        'scope',
        {
            PromptScope.GLOBAL: 'info',
            PromptScope.NICHE: 'warning',
            PromptScope.CHANNEL: 'success',
        },
        description=_('Scope'),
    )


@admin.register(PromptVersion)
class PromptVersionAdmin(ReelForgeAdmin):
    """Admin panel for PromptVersion."""

    list_display = (
        'template',
        'version',
        'model',
        'display_is_active',
    )
    list_filter = (
        ('is_active', ChoicesCheckboxFilter),
        ('model', ChoicesCheckboxFilter),
    )
    search_fields = ('template__key',)
    autocomplete_fields = ('template',)
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'template',
                    'version',
                    'model',
                    'is_active',
                    'temperature',
                    'max_tokens',
                ),
            },
        ),
        (
            _('Prompts'),
            {
                'classes': ('tab',),
                'fields': ('system_prompt', 'user_prompt'),
            },
        ),
    )

    display_is_active = make_boolean_badge_method(
        'is_active',
        description=_('Active'),
    )


@admin.register(StoryFormat)
class StoryFormatAdmin(ReelForgeAdmin):
    """Admin panel for StoryFormat."""

    list_display = (
        'key',
        'name',
        'fiction',
        'narration_pov',
        'display_is_active',
    )
    list_filter = (
        ('fiction', ChoicesCheckboxFilter),
        ('is_active', ChoicesCheckboxFilter),
    )
    search_fields = ('key', 'name')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'key',
                    'name',
                    'fiction',
                    'narration_pov',
                    'is_active',
                ),
            },
        ),
        (
            _('Beats'),
            {
                'classes': ('tab',),
                'fields': ('beats',),
            },
        ),
        (
            _('Pacing'),
            {
                'classes': ('tab',),
                'fields': ('pacing',),
            },
        ),
        (
            _('Overrides'),
            {
                'classes': ('tab',),
                'fields': ('prompt_overrides',),
            },
        ),
        (
            _('Music moods'),
            {
                'classes': ('tab',),
                'fields': ('music_mood_map',),
            },
        ),
    )

    display_is_active = make_boolean_badge_method(
        'is_active',
        description=_('Active'),
    )
