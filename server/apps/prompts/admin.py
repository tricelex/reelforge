"""Django admin registration for the prompts app."""

from typing import ClassVar

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


class PromptVersionInline(TabularInline):  # type: ignore[misc]
    """Inline editor for PromptVersion records."""

    model = PromptVersion
    extra = 0
    fields = ('version', 'model', 'is_active', 'temperature', 'max_tokens')


@admin.register(PromptTemplate)
class PromptTemplateAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for PromptTemplate."""

    list_display = ('key', 'name', 'scope')
    list_filter = ('scope',)
    search_fields = ('key', 'name')
    inlines: ClassVar = [PromptVersionInline]


@admin.register(PromptVersion)
class PromptVersionAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for PromptVersion."""

    list_display = ('template', 'version', 'model', 'is_active')
    list_filter = ('is_active', 'model')
    search_fields = ('template__key',)


@admin.register(StoryFormat)
class StoryFormatAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for StoryFormat."""

    list_display = ('key', 'name', 'fiction', 'narration_pov', 'is_active')
    list_filter = ('fiction', 'is_active')
    search_fields = ('key', 'name')
