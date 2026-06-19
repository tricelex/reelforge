"""Admin for core models."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from server.apps.core.models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin for UserProfile."""

    list_display = ('user', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__username',)
