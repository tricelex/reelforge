"""Admin registrations for the ideas app."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from server.apps.ideas.models import TopicIdea


@admin.register(TopicIdea)
class TopicIdeaAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for topic backlog items."""

    list_display = ('title', 'channel', 'status', 'score', 'created_at')
    list_filter = ('status',)
    search_fields = ('title', 'topic')
