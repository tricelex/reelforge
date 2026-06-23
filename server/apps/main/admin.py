from axes.admin import AccessAttemptAdmin as BaseAccessAttemptAdmin
from axes.admin import AccessFailureLogAdmin as BaseAccessFailureLogAdmin
from axes.admin import AccessLogAdmin as BaseAccessLogAdmin
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    RangeDateFilter,
)

from server.apps.main.models import BlogPost
from server.common.admin import ReelForgeAdmin

# Unregister auth and axes models so we can re-register them with Unfold's
# ModelAdmin base for consistent theming. These models are auto-registered by
# their respective apps, which load before server.apps.main in INSTALLED_APPS.
admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.unregister(AccessAttempt)
admin.site.unregister(AccessLog)
admin.site.unregister(AccessFailureLog)


@admin.register(BlogPost)
class BlogPostAdmin(ReelForgeAdmin):
    """Admin panel for BlogPost with Unfold enhancements."""

    list_display = ('title', 'created_at', 'updated_at')
    search_fields = ('title', 'body')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
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
class UserAdmin(BaseUserAdmin[User], ReelForgeAdmin):  # type: ignore[misc]
    """User admin using Unfold base for consistent theming."""

    list_filter = (
        ('is_staff', BooleanRadioFilter),
        ('is_active', BooleanRadioFilter),
        ('is_superuser', BooleanRadioFilter),
        ('date_joined', RangeDateFilter),
    )


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ReelForgeAdmin):  # type: ignore[misc]
    """Group admin using Unfold base for consistent theming."""


@admin.register(AccessAttempt)
class AccessAttemptAdmin(BaseAccessAttemptAdmin, ReelForgeAdmin):  # type: ignore[misc]
    """AccessAttempt admin using Unfold base for consistent theming."""


@admin.register(AccessLog)
class AccessLogAdmin(BaseAccessLogAdmin, ReelForgeAdmin):  # type: ignore[misc]
    """AccessLog admin using Unfold base for consistent theming."""


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(BaseAccessFailureLogAdmin, ReelForgeAdmin):  # type: ignore[misc]
    """AccessFailureLog admin using Unfold base for consistent theming."""
