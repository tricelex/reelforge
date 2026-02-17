from django.contrib.postgres.fields import ArrayField
from django.db import models

from reelforge.channels.choices import ChannelStatus
from reelforge.channels.choices import NicheCategory
from reelforge.core.models import BaseAbstractModel


class Channel(BaseAbstractModel):
    """A YouTube channel managed by the HQ.
    All pipeline entities belong to a channel.
    """

    # Identity
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=ChannelStatus.choices, default=ChannelStatus.SETUP)

    # YouTube credentials & IDs
    youtube_channel_id = models.CharField(max_length=100, blank=True, db_index=True)
    youtube_handle = models.CharField(max_length=100, blank=True)  # @handle
    oauth_credentials = models.JSONField(default=dict, blank=True)  # Encrypted in prod
    analytics_property = models.CharField(max_length=100, blank=True)

    # Niche configuration
    niche_category = models.CharField(max_length=30, choices=NicheCategory.choices)
    custom_niche = models.CharField(max_length=100, blank=True)
    target_niches = ArrayField(models.CharField(max_length=100), default=list)
    # e.g. ["personal finance", "investing for beginners", "side hustles"]

    # Target audience
    target_audience_description = models.TextField(blank=True)
    target_age_range = models.CharField(max_length=20, blank=True)  # "25-45"
    target_location = ArrayField(models.CharField(max_length=50), default=list)  # ["US", "UK", "NG"]

    # Content configuration
    content_tone = models.CharField(max_length=50, default="conversational_authoritative")
    video_length_min = models.PositiveSmallIntegerField(default=8)
    video_length_max = models.PositiveSmallIntegerField(default=14)
    upload_frequency = models.CharField(max_length=50, default="3x_per_week")
    # "daily" | "3x_per_week" | "2x_per_week" | "weekly"

    # Upload schedule (day + time per slot)
    upload_schedule = models.JSONField(
        default=list, help_text='[{"day": "Tuesday", "time": "15:00", "timezone": "America/New_York"}, ...]'
    )

    # Branding
    logo_file = models.FileField(upload_to="channels/logos/", null=True, blank=True)
    brand_color_hex = models.CharField(max_length=7, default="#FF4500")
    brand_color_secondary = models.CharField(max_length=7, default="#FFFFFF")
    font_primary = models.CharField(max_length=50, default="Montserrat")
    channel_intro_file = models.FileField(upload_to="channels/intros/", null=True, blank=True)
    channel_outro_file = models.FileField(upload_to="channels/outros/", null=True, blank=True)
    default_thumbnail_template = models.FileField(upload_to="channels/thumb_templates/", null=True, blank=True)

    # Voice configuration
    tts_provider = models.CharField(max_length=50, default="elevenlabs")
    tts_voice_id = models.CharField(max_length=100, blank=True)
    tts_voice_name = models.CharField(max_length=100, blank=True)
    tts_stability = models.FloatField(default=0.5)
    tts_similarity = models.FloatField(default=0.8)
    tts_style = models.FloatField(default=0.3)

    # Music preferences
    music_style = models.CharField(max_length=50, default="inspiring_cinematic")
    music_volume_pct = models.FloatField(default=0.08)

    # SEO & Monetization
    default_tags = ArrayField(models.CharField(max_length=100), default=list)
    channel_keywords = ArrayField(models.CharField(max_length=100), default=list)
    monetization_enabled = models.BooleanField(default=False)
    estimated_rpm_usd = models.DecimalField(max_digits=6, decimal_places=2, default=3.00)

    # API provider preferences (overrides global defaults)
    llm_provider = models.CharField(max_length=50, blank=True)  # blank = use global default
    image_provider = models.CharField(max_length=50, blank=True)
    video_provider = models.CharField(max_length=50, blank=True)

    # Pipeline automation config
    auto_approve_scripts = models.BooleanField(default=False)
    auto_approve_assets = models.BooleanField(default=False)
    auto_upload = models.BooleanField(default=False)
    auto_approve_delay_hrs = models.PositiveSmallIntegerField(default=12)

    # Boilerplate
    description_boilerplate = models.TextField(
        blank=True, help_text="Appended to every video description (links, disclaimer, socials)"
    )
    default_pinned_comment_template = models.TextField(blank=True)

    # Stats (denormalized for fast admin display)
    total_videos_published = models.PositiveIntegerField(default=0)
    total_views = models.PositiveBigIntegerField(default=0)
    total_subscribers = models.PositiveIntegerField(default=0)
    total_revenue_est_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_analytics_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} (@{self.youtube_handle or self.slug})"

    @property
    def active_niche(self) -> str:
        return (
            self.custom_niche if self.niche_category == self.NicheCategory.CUSTOM else self.get_niche_category_display()
        )


class ChannelCompetitor(BaseAbstractModel):
    """Competitor channels to monitor for gap analysis."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="competitors")
    youtube_channel_id = models.CharField(max_length=100)
    channel_name = models.CharField(max_length=255)
    channel_url = models.URLField()
    subscriber_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    last_analyzed = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["channel", "youtube_channel_id"]


class ChannelPlaylist(BaseAbstractModel):
    """YouTube playlists for organizing uploaded videos."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="playlists")
    youtube_playlist_id = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    niche_tag = models.CharField(max_length=100, blank=True)
    auto_assign = models.BooleanField(default=True)
    video_count = models.PositiveIntegerField(default=0)  # Create your models here.
