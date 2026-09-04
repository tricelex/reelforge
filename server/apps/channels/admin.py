"""Django admin registration for the channels app."""

from typing import Any, ClassVar

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import StackedInline, TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesCheckboxFilter,
)
from unfold.contrib.forms.widgets import ArrayWidget

from server.apps.channels.models import (
    AssemblyStyleConfig,
    Channel,
    ChannelBranding,
    Character,
    CharacterGenerationSession,
    CharacterSheetItem,
    CharacterStatus,
    FootageSourcingConfig,
    NicheConfig,
    YouTubeCredential,
)
from server.common.admin import ReelForgeAdmin
from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_boolean_badge_method,
    make_header_method,
    make_money_method,
)

_CHARACTER_STATUS_COLORS = {
    **STANDARD_STATUS_COLORS,
    CharacterStatus.DRAFT: 'info',
    CharacterStatus.APPROVED: 'success',
    CharacterStatus.RETIRED: 'warning',
}


class NicheConfigInline(StackedInline):  # type: ignore[misc]
    """Inline editor for the channel's niche configuration."""

    model = NicheConfig
    extra = 0
    tab = True


class ChannelBrandingInline(StackedInline):  # type: ignore[misc]
    """Inline editor for channel branding assets."""

    model = ChannelBranding
    extra = 0
    tab = True


class AssemblyStyleConfigInline(StackedInline):  # type: ignore[misc]
    """Inline editor for the channel's cinematic style pool."""

    model = AssemblyStyleConfig
    extra = 0
    tab = True


@admin.register(Channel)
class ChannelAdmin(ReelForgeAdmin):
    """Admin panel for Channel."""

    list_display = (
        'display_name',
        'display_kind',
        'display_publish_mode',
        'display_is_active',
    )
    list_filter = (
        ('kind', ChoicesCheckboxFilter),
        ('publish_mode', ChoicesCheckboxFilter),
        ('is_active', ChoicesCheckboxFilter),
    )
    search_fields = ('name',)
    inlines: ClassVar = [
        NicheConfigInline,
        ChannelBrandingInline,
        AssemblyStyleConfigInline,
    ]
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'name',
                    'kind',
                    'publish_mode',
                    'is_active',
                    'gates',
                    'character_design_mode',
                    'default_budget_usd',
                    'default_blueprint_name',
                    'provider_daily_caps',
                    'config_overrides',
                ),
            },
        ),
        (
            _('TTS'),
            {
                'classes': ('tab',),
                'fields': (
                    'voice_id',
                    'stability',
                    'similarity_boost',
                    'wpm',
                ),
            },
        ),
    )

    display_name = make_header_method(
        'display_name',
        _('Channel'),
        lambda obj: obj.name,
        lambda obj: obj.get_kind_display(),
    )
    display_kind = make_badge_method(
        'kind',
        {
            'LONGFORM': 'info',
            'SHORTS': 'success',
            'CLIPPING': 'warning',
        },
        description=_('Kind'),
    )
    display_publish_mode = make_badge_method(
        'publish_mode',
        {'auto': 'success', 'review': 'warning'},
        description=_('Publish mode'),
    )
    display_is_active = make_boolean_badge_method(
        'is_active',
        description=_('Active'),
    )


@admin.register(NicheConfig)
class NicheConfigAdmin(ReelForgeAdmin):
    """Admin panel for NicheConfig."""

    list_display = ('channel', 'format')
    search_fields = ('channel__name',)
    autocomplete_fields = ('channel', 'format')

    def get_form(
        self,
        request: object,
        obj: NicheConfig | None = None,
        *,
        change: bool = False,
        **kwargs: Any,
    ) -> type[Any]:
        """Use ArrayWidget with no preset choices for banned topics."""
        form = super().get_form(request, obj, change=change, **kwargs)
        array_fields = (
            'banned_topics',
            'style_tokens',
            'style_negatives',
        )
        for field_name in array_fields:
            form.base_fields[field_name].widget = ArrayWidget()
        return form  # type: ignore[no-any-return]


@admin.register(AssemblyStyleConfig)
class AssemblyStyleConfigAdmin(ReelForgeAdmin):
    """Admin panel for AssemblyStyleConfig."""

    list_display = (
        'channel',
        'camera_movements',
        'transition_styles',
        'min_cuts_per_minute',
        'max_cuts_per_minute',
        'music_bed_gain_db',
        'enable_background_music',
    )
    search_fields = ('channel__name',)
    autocomplete_fields = ('channel',)


@admin.register(FootageSourcingConfig)
class FootageSourcingConfigAdmin(ReelForgeAdmin):
    """Admin panel for FootageSourcingConfig."""

    list_display = (
        'channel',
        'sourcing_mode',
        'enabled_providers',
        'rerank_mode',
        'ai_fallback_enabled',
        'max_ai_fallback_per_run',
        'min_clip_width',
        'min_clip_duration_s',
        'require_attribution',
    )
    list_filter = (
        ('sourcing_mode', ChoicesCheckboxFilter),
        ('rerank_mode', ChoicesCheckboxFilter),
        ('ai_fallback_enabled', ChoicesCheckboxFilter),
        ('require_attribution', ChoicesCheckboxFilter),
    )
    search_fields = ('channel__name',)
    autocomplete_fields = ('channel',)


@admin.register(YouTubeCredential)
class YouTubeCredentialAdmin(ReelForgeAdmin):
    """Admin panel for YouTubeCredential."""

    list_display = ('channel', 'token_expiry')
    search_fields = ('channel__name',)
    autocomplete_fields = ('channel',)
    readonly_fields = (
        'access_token',
        'refresh_token',
        'scope',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': ('channel', 'token_expiry'),
            },
        ),
        (
            _('Tokens'),
            {
                'classes': ('collapse',),
                'fields': (
                    'access_token',
                    'refresh_token',
                    'scope',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )


class CharacterSheetItemInline(TabularInline):  # type: ignore[misc]
    """Inline editor for character sheet items."""

    model = CharacterSheetItem
    extra = 0
    tab = True


@admin.register(Character)
class CharacterAdmin(ReelForgeAdmin):
    """Admin panel for Character."""

    list_display = (
        'display_name',
        'channel',
        'display_status',
        'display_origin',
        'display_total_creation_cost_usd',
    )
    list_filter = (
        ('status', ChoicesCheckboxFilter),
        ('origin', ChoicesCheckboxFilter),
        ('channel', AutocompleteSelectFilter),
    )
    search_fields = ('name',)
    autocomplete_fields = ('channel', 'hero_ref', 'source_run')
    inlines: ClassVar = [CharacterSheetItemInline]

    display_name = make_header_method(
        'display_name',
        _('Character'),
        lambda obj: obj.name,
        lambda obj: str(obj.channel) if obj.channel else None,
    )
    display_status = make_badge_method(
        'status',
        _CHARACTER_STATUS_COLORS,
        description=_('Status'),
    )
    display_origin = make_badge_method(
        'origin',
        {'LIBRARY': 'info', 'RUN': 'success'},
        description=_('Origin'),
    )
    display_total_creation_cost_usd = make_money_method(
        'total_creation_cost_usd',
        description=_('Creation cost'),
    )


@admin.register(CharacterGenerationSession)
class CharacterGenerationSessionAdmin(ReelForgeAdmin):
    """Admin panel for CharacterGenerationSession."""

    list_display = ('character', 'created_at')
    search_fields = ('character__name',)
    autocomplete_fields = ('character',)
    readonly_fields = ('rounds', 'created_at', 'updated_at')
    fieldsets = (
        (
            None,
            {
                'fields': ('character', 'created_at', 'updated_at'),
            },
        ),
        (
            _('Rounds'),
            {
                'classes': ('tab',),
                'fields': ('rounds',),
            },
        ),
    )
