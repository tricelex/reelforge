"""Django admin registration for the channels app."""

from typing import ClassVar

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.channels.models import (
    Channel,
    ChannelBranding,
    Character,
    CharacterGenerationSession,
    CharacterSheetItem,
    NicheConfig,
    YouTubeCredential,
)


class NicheConfigInline(admin.StackedInline):  # type: ignore[type-arg]
    """Inline editor for the channel's niche configuration."""

    model = NicheConfig
    extra = 0


class ChannelBrandingInline(admin.StackedInline):  # type: ignore[type-arg]
    """Inline editor for channel branding assets."""

    model = ChannelBranding
    extra = 0


@admin.register(Channel)
class ChannelAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for Channel."""

    list_display = ('name', 'kind', 'publish_mode', 'is_active')
    list_filter = ('kind', 'publish_mode', 'is_active')
    search_fields = ('name',)
    inlines: ClassVar = [NicheConfigInline, ChannelBrandingInline]


@admin.register(NicheConfig)
class NicheConfigAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for NicheConfig."""

    list_display = ('channel', 'format')
    search_fields = ('channel__name',)


@admin.register(YouTubeCredential)
class YouTubeCredentialAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for YouTubeCredential."""

    list_display = ('channel',)
    search_fields = ('channel__name',)


class CharacterSheetItemInline(TabularInline):  # type: ignore[misc]
    """Inline editor for character sheet items."""

    model = CharacterSheetItem
    extra = 0


@admin.register(Character)
class CharacterAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for Character."""

    list_display = (
        'name',
        'channel',
        'status',
        'origin',
        'total_creation_cost_usd',
    )
    list_filter = ('status', 'origin')
    search_fields = ('name',)
    inlines: ClassVar = [CharacterSheetItemInline]


@admin.register(CharacterGenerationSession)
class CharacterGenerationSessionAdmin(ModelAdmin):  # type: ignore[misc]
    """Admin panel for CharacterGenerationSession."""

    list_display = ('character', 'created_at')
    search_fields = ('character__name',)
