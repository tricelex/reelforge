from django.contrib.postgres.fields import ArrayField
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel


class ChannelKind(models.TextChoices):
    LONGFORM = 'LONGFORM', 'Long-form'
    SHORTS = 'SHORTS', 'Shorts'
    CLIPPING = 'CLIPPING', 'Clipping'


class PublishMode(models.TextChoices):
    AUTO = 'auto', 'Auto'
    REVIEW = 'review', 'Review'


class CharacterDesignMode(models.TextChoices):
    INTERACTIVE = 'interactive', 'Interactive'
    AUTO = 'auto', 'Auto'
    NONE = 'none', 'None'


class CharacterStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    RETIRED = 'RETIRED', 'Retired'


class CharacterOrigin(models.TextChoices):
    LIBRARY = 'LIBRARY', 'Library'
    RUN = 'RUN', 'Run'


class Channel(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=ChannelKind.choices)
    publish_mode = models.CharField(
        max_length=10, choices=PublishMode.choices, default=PublishMode.REVIEW
    )
    # Gate keys that are armed for this channel (e.g. ['storyboard_gate', 'final_gate'])
    gates = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    character_design_mode = models.CharField(
        max_length=15,
        choices=CharacterDesignMode.choices,
        default=CharacterDesignMode.INTERACTIVE,
    )
    default_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # ElevenLabs TTS config
    voice_id = models.CharField(max_length=100, blank=True)
    stability = models.FloatField(default=0.5)
    similarity_boost = models.FloatField(default=0.75)
    wpm = models.PositiveIntegerField(default=158)  # words per minute for script pacing
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class NicheConfig(UUIDModel, TimeStampedModel):
    """Content configuration for one channel: audience, angle, format, lore."""

    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='niche_config'
    )
    # FK to prompts.StoryFormat — string ref; prompts app installed later in Phase 1
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
        models.CharField(max_length=200), default=list, blank=True
    )
    # Persistent lore document for fiction series (recurring universe)
    lore_document = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Niche config'

    def __str__(self) -> str:
        return f'NicheConfig for {self.channel}'


class YouTubeCredential(UUIDModel, TimeStampedModel):
    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='youtube_credential'
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)

    def __str__(self) -> str:
        return f'YouTubeCredential for {self.channel}'


class ChannelBranding(UUIDModel):
    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='branding'
    )
    # String refs to assets.LibraryAsset — assets app installed later in Phase 1
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
    fonts = models.ManyToManyField('assets.LibraryAsset', related_name='+', blank=True)
    music_pool_tags = ArrayField(
        models.CharField(max_length=40), default=list, blank=True
    )
    thumbnail_palette = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f'Branding for {self.channel}'


class Character(UUIDModel, TimeStampedModel):
    """An approved AI character with locked appearance prompt and reference image."""

    channel = models.ForeignKey(
        Channel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='characters',
    )
    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=10, choices=CharacterStatus.choices, default=CharacterStatus.DRAFT
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
        max_digits=8, decimal_places=4, default=0
    )
    origin = models.CharField(
        max_length=10, choices=CharacterOrigin.choices, default=CharacterOrigin.RUN
    )
    # source_run FK to pipelines.PipelineRun added in Phase 2 migration

    def __str__(self) -> str:
        return self.name


class CharacterSheetItem(UUIDModel):
    """Angle/expression/outfit variant for a character (front, profile, angry, etc.)."""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name='sheet'
    )
    asset = models.ForeignKey(
        'assets.LibraryAsset', on_delete=models.PROTECT, related_name='+'
    )
    label = models.CharField(max_length=60)

    def __str__(self) -> str:
        return f'{self.character} — {self.label}'


class CharacterGenerationSession(UUIDModel, TimeStampedModel):
    """One Studio iteration loop. Every round logged: prompt, refs, candidates, cost."""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name='sessions'
    )
    # run FK to pipelines.PipelineRun added in Phase 2 migration
    rounds = models.JSONField(default=list)

    def __str__(self) -> str:
        return f'Session for {self.character} ({self.created_at})'
