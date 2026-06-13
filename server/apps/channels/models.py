"""ORM models for the channels app."""

from typing import ClassVar, override

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
        models.CharField(max_length=40), default=list, blank=True,
    )
    character_design_mode = models.CharField(
        max_length=15,
        choices=CharacterDesignMode.choices,
        default=CharacterDesignMode.INTERACTIVE,
    )
    default_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    voice_id = models.CharField(max_length=100, blank=True)
    stability = models.FloatField(default=0.5)
    similarity_boost = models.FloatField(default=0.75)
    wpm = models.PositiveIntegerField(default=158)
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


class NicheConfig(UUIDModel, TimeStampedModel):
    """Content configuration for one channel: audience, angle, format, lore."""

    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='niche_config',
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
        models.CharField(max_length=200), default=list, blank=True,
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
        Channel, on_delete=models.CASCADE, related_name='youtube_credential',
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
        Channel, on_delete=models.CASCADE, related_name='branding',
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
        'assets.LibraryAsset', related_name='+', blank=True,
    )
    music_pool_tags = ArrayField(
        models.CharField(max_length=40), default=list, blank=True,
    )
    thumbnail_palette = models.JSONField(default=dict)

    @override
    def __str__(self) -> str:
        """Return branding reference."""
        return f'Branding for {self.channel}'


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
        max_digits=8, decimal_places=4, default=0,
    )
    origin = models.CharField(
        max_length=10,
        choices=CharacterOrigin.choices,
        default=CharacterOrigin.RUN,
    )
    # source_run FK to pipelines.PipelineRun added in Phase 2 migration

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
        Character, on_delete=models.CASCADE, related_name='sheet',
    )
    asset = models.ForeignKey(
        'assets.LibraryAsset', on_delete=models.PROTECT, related_name='+',
    )
    label = models.CharField(max_length=60)

    @override
    def __str__(self) -> str:
        """Return character and label."""
        return f'{self.character} — {self.label}'


class CharacterGenerationSession(UUIDModel, TimeStampedModel):
    """One Studio iteration: prompt, refs, candidates, cost per round."""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name='sessions',
    )
    # run FK to pipelines.PipelineRun added in Phase 2 migration
    rounds = models.JSONField(default=list)

    @override
    def __str__(self) -> str:
        """Return session identifier."""
        return f'Session for {self.character} ({self.created_at})'
