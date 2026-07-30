"""ORM models for the assets app."""

import uuid
from typing import ClassVar, override

from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models

from server.common.models import TimeStampedModel, UUIDModel


def asset_upload_path(instance: 'Asset', filename: str) -> str:
    """Build S3 key for a generated pipeline asset."""
    return f'generated/{instance.kind}/{uuid.uuid4()}/{filename}'


class AssetKind(models.TextChoices):
    """Kind of a pipeline-generated asset."""

    IMAGE = 'IMAGE', 'Image'
    VIDEO_SEGMENT = 'VIDEO_SEGMENT', 'Video Segment'
    AUDIO_VO = 'AUDIO_VO', 'Audio VO'
    SUBTITLE = 'SUBTITLE', 'Subtitle'
    FINAL_VIDEO = 'FINAL_VIDEO', 'Final Video'
    THUMBNAIL = 'THUMBNAIL', 'Thumbnail'
    TRANSCRIPT = 'TRANSCRIPT', 'Transcript'
    DOC = 'DOC', 'Document'
    FOOTAGE = 'FOOTAGE', 'Footage'


class LibraryAssetKind(models.TextChoices):
    """Kind of a human-curated library asset."""

    WATERMARK = 'WATERMARK', 'Watermark'
    INTRO = 'INTRO', 'Intro'
    OUTRO = 'OUTRO', 'Outro'
    OVERLAY = 'OVERLAY', 'Overlay'
    TRANSITION = 'TRANSITION', 'Transition'
    MUSIC = 'MUSIC', 'Music'
    SFX = 'SFX', 'SFX'
    FONT = 'FONT', 'Font'
    BACKGROUND = 'BACKGROUND', 'Background'
    VIDEO = 'VIDEO', 'Video'
    CHARACTER_REF = 'CHARACTER_REF', 'Character Ref'
    CAPTION_STYLE = 'CAPTION_STYLE', 'Caption Style'
    LUT = 'LUT', 'LUT'


class Asset(UUIDModel, TimeStampedModel):
    """Pipeline-generated asset — run-owned, immutable, stored in S3."""

    # FKs to pipelines.PipelineRun / StageExecution added in Phase 2 migration.
    kind = models.CharField(max_length=20, choices=AssetKind.choices)
    # Uses default storage (AssetStorage in prod, FileSystemStorage in tests).
    file = models.FileField(upload_to=asset_upload_path)
    mime = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64, db_index=True)
    meta = models.JSONField(default=dict)

    # Added in Phase 2 — nullable so Phase 1 rows are unaffected
    run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assets',
        db_index=True,
    )
    stage_execution = models.ForeignKey(
        'pipelines.StageExecution',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assets',
        db_index=True,
    )

    class Meta:
        """Meta options for Asset."""

        constraints: ClassVar = [
            models.CheckConstraint(
                name='assets_asset_kind_valid',
                condition=models.Q(kind__in=AssetKind.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return a readable identifier for this asset."""
        return f'{self.kind} {self.id}'


class LibraryAssetLicense(models.TextChoices):
    """Licensing basis for a human-curated library asset (esp. music/SFX)."""

    UNSPECIFIED = 'UNSPECIFIED', 'Unspecified'
    OWNED = 'OWNED', 'Owned / original'
    LICENSED = 'LICENSED', 'Licensed (paid)'
    CREATIVE_COMMONS = 'CREATIVE_COMMONS', 'Creative Commons'
    ROYALTY_FREE_VERIFIED = 'ROYALTY_FREE_VERIFIED', 'Royalty-free (verified)'


class LibraryAsset(UUIDModel, TimeStampedModel):
    """Human-curated, reusable, versioned asset (music, watermark, font…)."""

    kind = models.CharField(max_length=20, choices=LibraryAssetKind.choices)
    name = models.CharField(max_length=120)
    file = models.FileField(upload_to='library/')
    mime = models.CharField(max_length=64, blank=True, default='')
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
    license_type = models.CharField(
        max_length=25,
        choices=LibraryAssetLicense.choices,
        default=LibraryAssetLicense.UNSPECIFIED,
    )
    license_note = models.TextField(blank=True)

    class Meta:
        """Meta options for LibraryAsset."""

        constraints: ClassVar = [
            models.CheckConstraint(
                name='assets_libraryasset_kind_valid',
                condition=models.Q(kind__in=LibraryAssetKind.values),
            ),
            models.CheckConstraint(
                name='assets_libraryasset_license_type_valid',
                condition=models.Q(
                    license_type__in=LibraryAssetLicense.values,
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return the asset name."""
        return self.name


class AssetRendition(UUIDModel, TimeStampedModel):
    """Pre-transcoded variant of a LibraryAsset for a given output profile."""

    source = models.ForeignKey(
        LibraryAsset,
        on_delete=models.CASCADE,
        related_name='renditions',
    )
    profile = models.CharField(max_length=40)
    file = models.FileField(upload_to='renditions/')

    @override
    def __str__(self) -> str:
        """Return source name and profile."""
        return f'{self.source.name} [{self.profile}]'


class FootageCredit(UUIDModel, TimeStampedModel):
    """Licence provenance for one sourced footage asset."""

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name='credits',
    )
    run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='footage_credits',
        db_index=True,
    )
    scene_idx = models.PositiveIntegerField()
    provider = models.CharField(max_length=32, db_index=True)
    license = models.CharField(max_length=64)
    license_url = models.URLField(blank=True, default='')
    author = models.CharField(max_length=200, blank=True, default='')
    source_url = models.URLField()
    title = models.CharField(max_length=300, blank=True, default='')
    attribution_required = models.BooleanField(default=False)

    class Meta:
        """Meta options for FootageCredit."""

        ordering: ClassVar = ['scene_idx']

    @override
    def __str__(self) -> str:
        """Return provider, licence, and scene for admin display."""
        return f'{self.provider} {self.license} (scene {self.scene_idx})'
