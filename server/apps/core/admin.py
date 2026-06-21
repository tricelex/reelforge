"""Admin for core models."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import ChoicesCheckboxFilter

from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import make_badge_method


@admin.register(UserProfile)
class UserProfileAdmin(ReelForgeAdmin):
    """Admin for UserProfile."""

    list_display = ('user', 'display_role', 'created_at')
    list_filter = (('role', ChoicesCheckboxFilter),)
    search_fields = ('user__username',)
    autocomplete_fields = ('user',)

    display_role = make_badge_method(
        'role',
        {
            UserRole.OPERATOR: 'info',
            UserRole.REVIEWER: 'warning',
        },
        description=_('Role'),
    )
