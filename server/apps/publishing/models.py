"""Models for the publishing app."""

from typing import ClassVar, override

from django.db import models

from server.common.models import TimeStampedModel, UUIDModel


class PublishStatus(models.TextChoices):
    """Lifecycle status of a PublishJob."""

    PENDING = 'PENDING', 'Pending'
    UPLOADING = 'UPLOADING', 'Uploading'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'


class PublishJob(UUIDModel, TimeStampedModel):
    """One YouTube upload initiated by the publish pipeline stage."""

    run = models.ForeignKey(
        'pipelines.PipelineRun',
        on_delete=models.PROTECT,
        related_name='publish_jobs',
    )
    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.PROTECT,
        related_name='publish_jobs',
    )
    youtube_video_id = models.CharField(max_length=20, blank=True)
    status = models.CharField(
        max_length=10,
        choices=PublishStatus.choices,
        default=PublishStatus.PENDING,
    )
    schedule_at = models.DateTimeField(null=True, blank=True)
    metadata_snapshot = models.JSONField(default=dict)
    thumbnail_asset_id = models.CharField(max_length=64, blank=True, default='')
    thumbnail_tested = models.BooleanField(default=False)
    tested_candidate_ranks = models.JSONField(default=list, blank=True)
    error = models.JSONField(null=True, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='publishing_publishjob_status_valid',
                condition=models.Q(status__in=PublishStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'PublishJob {self.id} ({self.status})'
