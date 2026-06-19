"""Admin registrations for the ideas app."""

from django.contrib.admin import ModelAdmin, register

from server.apps.ideas.models import TopicIdea


@register(TopicIdea)
class TopicIdeaAdmin(ModelAdmin):  # type: ignore[type-arg]
    """Admin for topic backlog items."""

    list_display = ('title', 'channel', 'status', 'score', 'created_at')
    list_filter = ('status',)
    search_fields = ('title', 'topic')
