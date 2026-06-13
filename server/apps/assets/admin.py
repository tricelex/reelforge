"""Django admin registration for the assets app."""

from typing import ClassVar

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.assets.models import Asset, AssetRendition, LibraryAsset


class AssetRenditionInline(TabularInline):  # type: ignore[misc]
    """Inline editor for AssetRendition records."""

    model = AssetRendition
    extra = 0
    fields = ('profile', 'file')
    readonly_fields: ClassVar = ('profile',)


@admin.register(LibraryAsset)
class LibraryAssetAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for LibraryAsset."""

    list_display = ('name', 'kind', 'channel', 'version', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('name',)
    inlines: ClassVar = [AssetRenditionInline]


@admin.register(Asset)
class AssetAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for generated pipeline Assets (read-only)."""

    list_display = ('kind', 'mime', 'checksum', 'created_at')
    list_filter = ('kind',)
    search_fields = ('checksum',)
    readonly_fields: ClassVar = (
        'checksum', 'mime', 'meta', 'created_at', 'updated_at',
    )


@admin.register(AssetRendition)
class AssetRenditionAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for AssetRendition."""

    list_display = ('source', 'profile')
    list_filter = ('profile',)
    search_fields = ('source__name',)
