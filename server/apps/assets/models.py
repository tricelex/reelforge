import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel
from server.common.s3 import AssetStorage

_s3 = AssetStorage()


def _asset_upload_path(instance: 'Asset', filename: str) -> str:
    return f'generated/{instance.kind}/{uuid.uuid4()}/{filename}'


class AssetKind(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO_SEGMENT = 'VIDEO_SEGMENT', 'Video Segment'
    AUDIO_VO = 'AUDIO_VO', 'Audio VO'
    SUBTITLE = 'SUBTITLE', 'Subtitle'
    FINAL_VIDEO = 'FINAL_VIDEO', 'Final Video'
    THUMBNAIL = 'THUMBNAIL', 'Thumbnail'
    TRANSCRIPT = 'TRANSCRIPT', 'Transcript'
    DOC = 'DOC', 'Document'


class LibraryAssetKind(models.TextChoices):
    WATERMARK = 'WATERMARK', 'Watermark'
    INTRO = 'INTRO', 'Intro'
    OUTRO = 'OUTRO', 'Outro'
    OVERLAY = 'OVERLAY', 'Overlay'
    TRANSITION = 'TRANSITION', 'Transition'
    MUSIC = 'MUSIC', 'Music'
    SFX = 'SFX', 'SFX'
    FONT = 'FONT', 'Font'
    BACKGROUND = 'BACKGROUND', 'Background'
    CHARACTER_REF = 'CHARACTER_REF', 'Character Ref'
    CAPTION_STYLE = 'CAPTION_STYLE', 'Caption Style'
    LUT = 'LUT', 'LUT'


class Asset(UUIDModel, TimeStampedModel):
    """Pipeline-generated asset — run-owned, immutable, stored in S3."""

    # FKs to pipelines.PipelineRun / StageExecution added in Phase 2 migration.
    kind = models.CharField(max_length=20, choices=AssetKind.choices)
    file = models.FileField(storage=_s3, upload_to=_asset_upload_path)
    mime = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64, db_index=True)
    meta = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name='assets_asset_kind_valid',
                condition=models.Q(kind__in=AssetKind.values),
            ),
        ]

    def __str__(self) -> str:
        return f'{self.kind} {self.id}'


class LibraryAsset(UUIDModel, TimeStampedModel):
    """Human-curated, reusable, versioned asset (music, watermark, font, etc.)."""

    kind = models.CharField(max_length=20, choices=LibraryAssetKind.choices)
    name = models.CharField(max_length=120)
    file = models.FileField(storage=_s3, upload_to='library/')
    tags = ArrayField(models.CharField(max_length=40), default=list)
    channel = models.ForeignKey(
        'channels.Channel',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='library_assets',
    )
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    meta = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name='assets_libraryasset_kind_valid',
                condition=models.Q(kind__in=LibraryAssetKind.values),
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AssetRendition(UUIDModel, TimeStampedModel):
    """Pre-transcoded variant of a LibraryAsset for a specific output profile."""

    source = models.ForeignKey(
        LibraryAsset, on_delete=models.CASCADE, related_name='renditions'
    )
    profile = models.CharField(max_length=40)
    file = models.FileField(storage=_s3, upload_to='renditions/')

    def __str__(self) -> str:
        return f'{self.source.name} [{self.profile}]'
