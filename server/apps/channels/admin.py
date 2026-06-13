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


class NicheConfigInline(admin.StackedInline):
    model = NicheConfig
    extra = 0


class ChannelBrandingInline(admin.StackedInline):
    model = ChannelBranding
    extra = 0


@admin.register(Channel)
class ChannelAdmin(ModelAdmin):
    list_display = ('name', 'kind', 'publish_mode', 'is_active')
    list_filter = ('kind', 'publish_mode', 'is_active')
    search_fields = ('name',)
    inlines = [NicheConfigInline, ChannelBrandingInline]


@admin.register(NicheConfig)
class NicheConfigAdmin(ModelAdmin):
    list_display = ('channel', 'format')
    search_fields = ('channel__name',)


@admin.register(YouTubeCredential)
class YouTubeCredentialAdmin(ModelAdmin):
    list_display = ('channel',)
    search_fields = ('channel__name',)


class CharacterSheetItemInline(TabularInline):
    model = CharacterSheetItem
    extra = 0


@admin.register(Character)
class CharacterAdmin(ModelAdmin):
    list_display = ('name', 'channel', 'status', 'origin', 'total_creation_cost_usd')
    list_filter = ('status', 'origin')
    search_fields = ('name',)
    inlines = [CharacterSheetItemInline]


@admin.register(CharacterGenerationSession)
class CharacterGenerationSessionAdmin(ModelAdmin):
    list_display = ('character', 'created_at')
    search_fields = ('character__name',)
