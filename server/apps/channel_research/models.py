"""ORM models for the channel research app."""

from typing import ClassVar, override

from django.conf import settings
from django.db import models

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
)
from server.common.models import TimeStampedModel, UUIDModel


class ChannelResearchJob(UUIDModel, TimeStampedModel):
    """Pre-channel research run that stores a dossier and ChannelSpec."""

    source_channel_url = models.CharField(max_length=500)
    target_market = models.CharField(max_length=200, blank=True)
    working_name = models.CharField(max_length=120, blank=True)
    kind = models.CharField(
        max_length=10,
        choices=ChannelResearchKind.choices,
        default=ChannelResearchKind.LONGFORM,
    )
    notes = models.TextField(blank=True)
    source_channel_id = models.CharField(max_length=64, blank=True)
    source_channel_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=12,
        choices=ChannelResearchStatus.choices,
        default=ChannelResearchStatus.PENDING,
    )
    research_report = models.JSONField(default=dict, blank=True)
    channel_spec = models.JSONField(default=dict, blank=True)
    tool_trace = models.JSONField(default=list, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='channel_research_jobs',
    )

    class Meta:
        ordering: ClassVar = ['-created_at']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='channel_research_job_status_valid',
                condition=models.Q(
                    status__in=ChannelResearchStatus.values,
                ),
            ),
            models.CheckConstraint(
                name='channel_research_job_kind_valid',
                condition=models.Q(
                    kind__in=ChannelResearchKind.values,
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        label = self.working_name or self.source_channel_url
        return label[:60]
