from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.prompts.models import PromptTemplate, PromptVersion, StoryFormat


class PromptVersionInline(TabularInline):
    model = PromptVersion
    extra = 0
    fields = ('version', 'model', 'is_active', 'temperature', 'max_tokens')


@admin.register(PromptTemplate)
class PromptTemplateAdmin(ModelAdmin):
    list_display = ('key', 'name', 'scope')
    list_filter = ('scope',)
    search_fields = ('key', 'name')
    inlines = [PromptVersionInline]


@admin.register(PromptVersion)
class PromptVersionAdmin(ModelAdmin):
    list_display = ('template', 'version', 'model', 'is_active')
    list_filter = ('is_active', 'model')
    search_fields = ('template__key',)


@admin.register(StoryFormat)
class StoryFormatAdmin(ModelAdmin):
    list_display = ('key', 'name', 'fiction', 'narration_pov', 'is_active')
    list_filter = ('fiction', 'is_active')
    search_fields = ('key', 'name')
