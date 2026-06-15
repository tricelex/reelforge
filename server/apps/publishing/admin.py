"""Django admin registration for the publishing app."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from server.apps.publishing.models import PublishJob


@admin.register(PublishJob)
class PublishJobAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for PublishJob."""

    list_display = ('id', 'channel', 'status', 'youtube_video_id', 'created_at')
    list_filter = ('status',)
    readonly_fields = ('id', 'created_at', 'updated_at')
