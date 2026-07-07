"""ORM models for the ideas app."""

from typing import ClassVar, override

from django.db import models

from server.apps.ideas.logic.constants import IdeaStatus
from server.common.models import TimeStampedModel, UUIDModel


class TopicIdea(UUIDModel, TimeStampedModel):
    """Pre-pipeline topic backlog item for longform channels."""

    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.CASCADE,
        related_name='topic_ideas',
    )
    niche = models.ForeignKey(
        'channels.NicheConfig',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='topic_ideas',
    )
    title = models.CharField(max_length=200)
    topic = models.TextField()
    score = models.FloatField(default=0.0)
    status = models.CharField(
        max_length=10,
        choices=IdeaStatus.choices,
        default=IdeaStatus.BACKLOG,
    )
    run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='source_ideas',
    )
    metadata = models.JSONField(default=dict, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar = ['-score', '-created_at']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='ideas_topicidea_status_valid',
                condition=models.Q(status__in=IdeaStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.title[:60]


class NicheOutlierScan(UUIDModel, TimeStampedModel):
    """A cached outlier-video scan for one niche, refreshed at most daily."""

    niche = models.ForeignKey(
        'channels.NicheConfig',
        on_delete=models.CASCADE,
        related_name='outlier_scans',
    )
    query = models.CharField(max_length=200)
    results = models.JSONField(default=list)

    class Meta:
        ordering: ClassVar = ['-created_at']

    @override
    def __str__(self) -> str:
        return f'Outlier scan for {self.niche_id} ({self.created_at})'
