"""ORM models for the channels app."""

from typing import ClassVar, Final, override

from django.contrib.postgres.fields import ArrayField
from django.db import models

from server.common.models import TimeStampedModel, UUIDModel


class ChannelKind(models.TextChoices):
    """Top-level content format a channel produces."""

    LONGFORM = 'LONGFORM', 'Long-form'
    SHORTS = 'SHORTS', 'Shorts'
    CLIPPING = 'CLIPPING', 'Clipping'


class PublishMode(models.TextChoices):
    """Whether the channel auto-publishes or holds for human review."""

    AUTO = 'auto', 'Auto'
    REVIEW = 'review', 'Review'


class CharacterDesignMode(models.TextChoices):
    """How the channel's AI character is chosen or generated."""

    INTERACTIVE = 'interactive', 'Interactive'
    AUTO = 'auto', 'Auto'
    NONE = 'none', 'None'


class SourcingMode(models.TextChoices):
    """Which family of providers a channel prefers."""

    STOCK_FIRST = 'stock_first', 'Stock first'
    ARCHIVAL_FIRST = 'archival_first', 'Archival first'
    BALANCED = 'balanced', 'Balanced'


# Aligns with reelforge-frontend PROVIDER_OPTIONS / stock-first cascade.
DEFAULT_ENABLED_PROVIDERS: Final[tuple[str, ...]] = (
    'pexels',
    'pixabay',
    'wikimedia',
    'openverse',
    'archive_org',
)


def _default_enabled_providers() -> list[str]:
    """Callable default for FootageSourcingConfig.enabled_providers."""
    return list(DEFAULT_ENABLED_PROVIDERS)


class RerankMode(models.TextChoices):
    """How footage candidates are scored before selection."""

    VISION = 'vision', 'Vision model'
    METADATA = 'metadata', 'Metadata only'
    NONE = 'none', 'No re-ranking'


class CharacterStatus(models.TextChoices):
    """Lifecycle state of a Character."""

    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    RETIRED = 'RETIRED', 'Retired'


class CharacterOrigin(models.TextChoices):
    """Where the character reference image came from."""

    LIBRARY = 'LIBRARY', 'Library'
    RUN = 'RUN', 'Run'


class Channel(UUIDModel, TimeStampedModel):
    """A YouTube channel with its production config and TTS settings."""

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=ChannelKind.choices)
    publish_mode = models.CharField(
        max_length=10,
        choices=PublishMode.choices,
        default=PublishMode.REVIEW,
    )
    # Gate keys that are armed for this channel (e.g. ['storyboard_gate'])
    gates = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    character_design_mode = models.CharField(
        max_length=15,
        choices=CharacterDesignMode.choices,
        default=CharacterDesignMode.INTERACTIVE,
    )
    default_budget_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    max_publishes_per_day = models.PositiveSmallIntegerField(default=1)
    voice_id = models.CharField(max_length=100, blank=True)
    stability = models.FloatField(default=0.5)
    similarity_boost = models.FloatField(default=0.75)
    wpm = models.PositiveIntegerField(default=158)
    default_blueprint_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
    )
    provider_daily_caps = models.JSONField(default=list, blank=True)
    config_overrides = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        """Meta options for Channel."""

        ordering: ClassVar = ['name']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='channels_channel_kind_valid',
                condition=models.Q(kind__in=ChannelKind.values),
            ),
            models.CheckConstraint(
                name='channels_channel_publish_mode_valid',
                condition=models.Q(publish_mode__in=PublishMode.values),
            ),
            models.CheckConstraint(
                name='channels_channel_character_design_mode_valid',
                condition=models.Q(
                    character_design_mode__in=CharacterDesignMode.values,
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return channel name."""
        return self.name

    @property
    def assembly_style_camera_movements(self) -> list[str]:
        """Camera-movement pool from the AssemblyStyleConfig, or []."""
        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.camera_movements)

    @property
    def assembly_style_transition_styles(self) -> list[str]:
        """Transition-style pool from the AssemblyStyleConfig, or []."""
        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.transition_styles)

    @property
    def assembly_style_sfx_pool_tags(self) -> list[str]:
        """SFX tag pool from the AssemblyStyleConfig, or []."""
        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.sfx_pool_tags)

    def footage_sourcing_or_default(self) -> 'FootageSourcingConfig':
        """Return this channel's footage config, or unsaved defaults."""
        try:
            return self.footage_sourcing
        except FootageSourcingConfig.DoesNotExist:
            return FootageSourcingConfig(
                channel=self,
                id=None,
                enabled_providers=_default_enabled_providers(),
            )


class NicheConfig(UUIDModel, TimeStampedModel):
    """Content configuration for one channel: audience, angle, format, lore."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='niche_config',
    )
    format = models.ForeignKey(
        'prompts.StoryFormat',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    audience = models.TextField(blank=True)
    angle = models.TextField(blank=True)
    banned_topics = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
    )
    lore_document = models.TextField(blank=True)

    class Meta:
        """Meta options for NicheConfig."""

        verbose_name = 'Niche config'

    @override
    def __str__(self) -> str:
        """Return a reference to the parent channel."""
        return f'NicheConfig for {self.channel}'


class YouTubeCredential(UUIDModel, TimeStampedModel):
    """OAuth2 tokens for the YouTube Data API for one channel."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='youtube_credential',
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)

    @override
    def __str__(self) -> str:
        """Return a reference to the parent channel."""
        return f'YouTubeCredential for {self.channel}'


class ChannelBranding(UUIDModel):
    """Branding assets and style config attached to a channel."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='branding',
    )
    intro = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    outro = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    watermark = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    watermark_position = models.CharField(max_length=20, default='bottom_right')
    watermark_opacity = models.FloatField(default=0.6)
    caption_style = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    fonts = models.ManyToManyField(
        'assets.LibraryAsset',
        related_name='+',
        blank=True,
    )
    music_pool_tags = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    thumbnail_palette = models.JSONField(default=dict)

    @override
    def __str__(self) -> str:
        """Return branding reference."""
        return f'Branding for {self.channel}'


_DEFAULT_CAMERA_MOVEMENTS = ['push_in', 'pan_left', 'pan_right', 'static_hold']
_DEFAULT_TRANSITION_STYLES = ['hard_cut', 'cross_dissolve']


class AssemblyStyleConfig(UUIDModel):
    """Per-channel cinematic fingerprint: movement, transitions, SFX, pacing."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='assembly_style',
    )
    camera_movements = ArrayField(
        models.CharField(max_length=30),
        default=list,
        blank=True,
    )
    transition_styles = ArrayField(
        models.CharField(max_length=30),
        default=list,
        blank=True,
    )
    sfx_pool_tags = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    min_cuts_per_minute = models.PositiveSmallIntegerField(default=4)
    max_cuts_per_minute = models.PositiveSmallIntegerField(default=8)
    music_bed_gain_db = models.FloatField(
        default=-22.0,
        help_text='Background music gain in dB relative to dialogue.',
    )
    enable_background_music = models.BooleanField(
        default=True,
        help_text='When false, assembly mixes voiceover only (no music bed).',
    )

    @override
    def __str__(self) -> str:
        """Return assembly style reference."""
        return f'AssemblyStyleConfig for {self.channel}'


class Character(UUIDModel, TimeStampedModel):
    """AI character with locked appearance prompt and reference image."""

    channel = models.ForeignKey(
        Channel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='characters',
    )
    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=10,
        choices=CharacterStatus.choices,
        default=CharacterStatus.DRAFT,
    )
    appearance_prompt = models.TextField()
    persona = models.TextField(blank=True)
    hero_ref = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    total_creation_cost_usd = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=0,
    )
    origin = models.CharField(
        max_length=10,
        choices=CharacterOrigin.choices,
        default=CharacterOrigin.RUN,
    )
    # Added in Phase 2 — nullable so Phase 1 rows are unaffected
    source_run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        db_index=True,
    )

    class Meta:
        """Meta options for Character."""

        constraints: ClassVar = [
            models.CheckConstraint(
                name='channels_character_status_valid',
                condition=models.Q(status__in=CharacterStatus.values),
            ),
            models.CheckConstraint(
                name='channels_character_origin_valid',
                condition=models.Q(origin__in=CharacterOrigin.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return character name."""
        return self.name


class CharacterSheetItem(UUIDModel):
    """Angle/expression/outfit variant for a character."""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='sheet',
    )
    asset = models.ForeignKey(
        'assets.LibraryAsset',
        on_delete=models.PROTECT,
        related_name='+',
    )
    label = models.CharField(max_length=60)

    @override
    def __str__(self) -> str:
        """Return character and label."""
        return f'{self.character} — {self.label}'


class CharacterGenerationSession(UUIDModel, TimeStampedModel):
    """One Studio iteration: prompt, refs, candidates, cost per round."""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    # run FK to pipelines.PipelineRun added in Phase 2 migration
    rounds = models.JSONField(default=list)

    @override
    def __str__(self) -> str:
        """Return session identifier."""
        return f'Session for {self.character} ({self.created_at})'


class FootageSourcingConfig(UUIDModel, TimeStampedModel):
    """Per-channel stock/archival footage sourcing rules."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='footage_sourcing',
    )
    enabled_providers = ArrayField(
        models.CharField(max_length=32),
        default=_default_enabled_providers,
        blank=True,
        help_text='Ordered provider priority. Order is significant.',
    )
    sourcing_mode = models.CharField(
        max_length=15,
        choices=SourcingMode.choices,
        default=SourcingMode.STOCK_FIRST,
    )
    ai_fallback_enabled = models.BooleanField(default=True)
    rerank_mode = models.CharField(
        max_length=10,
        choices=RerankMode.choices,
        default=RerankMode.VISION,
    )
    candidates_per_scene = models.PositiveSmallIntegerField(default=8)
    min_clip_width = models.PositiveIntegerField(default=1280)
    min_clip_duration_s = models.FloatField(default=3.0)
    allowed_licenses = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    require_attribution = models.BooleanField(default=True)

    class Meta:
        """Meta options for FootageSourcingConfig."""

        verbose_name = 'Footage sourcing config'
        constraints: ClassVar = [
            models.CheckConstraint(
                name='channels_footagesourcing_mode_valid',
                condition=models.Q(sourcing_mode__in=SourcingMode.values),
            ),
            models.CheckConstraint(
                name='channels_footagesourcing_rerank_valid',
                condition=models.Q(rerank_mode__in=RerankMode.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return a reference to the parent channel."""
        return f'FootageSourcingConfig for {self.channel}'
