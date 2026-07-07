"""Django admin registration for the assets app."""

from typing import ClassVar

from django.contrib import admin
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from unfold.admin import TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
    RangeDateTimeFilter,
)

from server.apps.assets.models import Asset, AssetRendition, LibraryAsset
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    make_boolean_badge_method,
    make_header_method,
)


class AssetRenditionInline(TabularInline):  # type: ignore[misc]
    """Inline editor for AssetRendition records."""

    model = AssetRendition
    extra = 0
    tab = True
    fields = ('profile', 'file')
    readonly_fields: ClassVar = ('profile',)

    def get_queryset(self, request: object) -> QuerySet[AssetRendition]:
        """Prefetch source for inline titles (__str__ reads source.name)."""
        return super().get_queryset(request).select_related('source')  # type: ignore[no-any-return]


@admin.register(LibraryAsset)
class LibraryAssetAdmin(ReelForgeAdmin):
    """Admin panel for LibraryAsset."""

    list_display = (
        'display_name',
        'kind',
        'channel',
        'version',
        'display_is_active',
    )
    list_filter = (
        ('kind', ChoicesCheckboxFilter),
        ('is_active', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
    )
    search_fields = ('name',)
    autocomplete_fields = ('channel',)
    readonly_fields = ('meta', 'created_at', 'updated_at')
    inlines: ClassVar = [AssetRenditionInline]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'name',
                    'kind',
                    'file',
                    'mime',
                    'tags',
                    'channel',
                    'version',
                    'is_active',
                ),
            },
        ),
        (
            _('Metadata'),
            {
                'classes': ('tab',),
                'fields': ('meta',),
            },
        ),
    )

    display_name = make_header_method(
        'display_name',
        _('Asset'),
        lambda obj: obj.name,
        lambda obj: obj.mime or None,
    )
    display_is_active = make_boolean_badge_method(
        'is_active',
        description=_('Active'),
    )


@admin.register(Asset)
class AssetAdmin(ReelForgeAdmin):
    """Admin panel for generated pipeline Assets (read-only)."""

    list_display = (
        'kind',
        'mime',
        'run',
        'stage_execution',
        'checksum',
        'created_at',
    )
    list_filter = (
        ('kind', ChoicesCheckboxFilter),
        ('run', AutocompleteSelectFilter),
        ('stage_execution', AutocompleteSelectFilter),
        ('created_at', RangeDateTimeFilter),
    )
    search_fields = ('checksum', 'run__topic')
    list_select_related: ClassVar = ('run', 'stage_execution')
    readonly_fields: ClassVar = (
        'kind',
        'file',
        'mime',
        'checksum',
        'meta',
        'run',
        'stage_execution',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'kind',
                    'file',
                    'mime',
                    'checksum',
                    'run',
                    'stage_execution',
                ),
            },
        ),
        (
            _('Metadata'),
            {
                'classes': ('tab',),
                'fields': ('meta',),
            },
        ),
        (
            _('Timestamps'),
            {
                'classes': ('tab',),
                'fields': ('created_at', 'updated_at'),
            },
        ),
    )

    def has_add_permission(self, request: object) -> bool:
        """Generated assets are created by the pipeline only."""
        return False

    def has_change_permission(
        self,
        request: object,
        obj: Asset | None = None,
    ) -> bool:
        """Generated assets are immutable in admin."""
        return False


@admin.register(AssetRendition)
class AssetRenditionAdmin(ReelForgeAdmin):
    """Admin panel for AssetRendition."""

    list_display = ('source', 'profile')
    list_filter = (('profile', ChoicesCheckboxFilter),)
    search_fields = ('source__name',)
    autocomplete_fields = ('source',)

    def get_queryset(self, request: object) -> QuerySet[AssetRendition]:
        """Prefetch source for list_display."""
        return super().get_queryset(request).select_related('source')  # type: ignore[no-any-return]
