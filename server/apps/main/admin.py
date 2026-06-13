from axes.admin import AccessAttemptAdmin as BaseAccessAttemptAdmin
from axes.admin import AccessFailureLogAdmin as BaseAccessFailureLogAdmin
from axes.admin import AccessLogAdmin as BaseAccessLogAdmin
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin

from server.apps.main.models import BlogPost

# Unregister auth and axes models so we can re-register them with Unfold's
# ModelAdmin base for consistent theming. These models are auto-registered by
# their respective apps, which load before server.apps.main in INSTALLED_APPS.
admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.unregister(AccessAttempt)
admin.site.unregister(AccessLog)
admin.site.unregister(AccessFailureLog)


@admin.register(BlogPost)
class BlogPostAdmin(ModelAdmin[BlogPost]):  # type: ignore[misc]
    """Admin panel for BlogPost with Unfold enhancements."""

    list_display = ('title', 'created_at', 'updated_at')
    search_fields = ('title', 'body')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    compressed_fields = True
    warn_unsaved_form = True
    fieldsets = (
        ('Content', {'fields': ('title', 'body')}),
        (
            'Metadata',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin[User], ModelAdmin):  # type: ignore[misc]
    """User admin using Unfold base for consistent theming."""


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    """Group admin using Unfold base for consistent theming."""


@admin.register(AccessAttempt)
class AccessAttemptAdmin(BaseAccessAttemptAdmin, ModelAdmin):  # type: ignore[misc]
    """AccessAttempt admin using Unfold base for consistent theming."""


@admin.register(AccessLog)
class AccessLogAdmin(BaseAccessLogAdmin, ModelAdmin):  # type: ignore[misc]
    """AccessLog admin using Unfold base for consistent theming."""


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(BaseAccessFailureLogAdmin, ModelAdmin):  # type: ignore[misc]
    """AccessFailureLog admin using Unfold base for consistent theming."""
