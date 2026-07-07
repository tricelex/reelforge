from typing import ClassVar, override

from django.db import models

from server.common.models import TimeStampedModel, UUIDModel


class PipelineKind(models.TextChoices):
    """Blueprint kind — determines which stage graph to use."""

    LONGFORM = 'LONGFORM', 'Long-form'
    SHORTS = 'SHORTS', 'Shorts'
    CLIPPING = 'CLIPPING', 'Clipping'


class RunStatus(models.TextChoices):
    """Lifecycle status of a PipelineRun."""

    PENDING = 'PENDING', 'Pending'
    RUNNING = 'RUNNING', 'Running'
    AWAITING_REVIEW = 'AWAITING_REVIEW', 'Awaiting review'
    BUDGET_HOLD = 'BUDGET_HOLD', 'Budget hold'
    PUBLISH_HOLD = 'PUBLISH_HOLD', 'Publish hold'
    PUBLISHING = 'PUBLISHING', 'Publishing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class StageStatus(models.TextChoices):
    """Lifecycle status of a StageExecution."""

    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    RUNNING = 'RUNNING', 'Running'
    SUCCEEDED = 'SUCCEEDED', 'Succeeded'
    FAILED = 'FAILED', 'Failed'
    NEEDS_INPUT = 'NEEDS_INPUT', 'Needs input'
    SKIPPED = 'SKIPPED', 'Skipped'
    STALE = 'STALE', 'Stale'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CastDesignStatus(models.TextChoices):
    """Review state of a RunCast character assignment."""

    PROPOSED = 'PROPOSED', 'Proposed'
    APPROVED = 'APPROVED', 'Approved'
    DEMOTED = 'DEMOTED', 'Demoted'


class PipelineBlueprint(UUIDModel, TimeStampedModel):
    """Versioned DAG definition that drives pipeline execution."""

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=PipelineKind.choices)
    graph = models.JSONField()
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering: ClassVar = ['name']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='pipelines_pipelineblueprint_kind_valid',
                condition=models.Q(kind__in=PipelineKind.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.name} v{self.version}'


class PipelineRun(UUIDModel, TimeStampedModel):
    """One execution of a PipelineBlueprint for a given channel and topic."""

    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.PROTECT,
        related_name='runs',
    )
    blueprint = models.ForeignKey(
        PipelineBlueprint,
        on_delete=models.PROTECT,
        related_name='runs',
    )
    blueprint_snapshot = models.JSONField()
    prompt_snapshot = models.JSONField(default=dict)
    topic = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=RunStatus.choices,
        default=RunStatus.PENDING,
    )
    total_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
    )
    script_embedding = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    is_paused = models.BooleanField(default=False)
    had_manual_edits = models.BooleanField(default=False)
    source_idea = models.ForeignKey(
        'ideas.TopicIdea',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='promoted_runs',
    )

    class Meta:
        ordering: ClassVar = ['-created_at']
        constraints: ClassVar = [
            models.CheckConstraint(
                name='pipelines_pipelinerun_status_valid',
                condition=models.Q(status__in=RunStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'Run {self.id} ({self.status})'


class StageExecution(UUIDModel, TimeStampedModel):
    """One attempt at executing a single stage within a PipelineRun."""

    run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name='stages',
        db_index=True,
    )
    stage_key = models.CharField(max_length=64, db_index=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children',
    )
    shard_index = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=15,
        choices=StageStatus.choices,
        default=StageStatus.PENDING,
    )
    attempt = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    input_hash = models.CharField(max_length=64, db_index=True, blank=True)
    input_snapshot = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    error = models.JSONField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    queue = models.CharField(max_length=32, default='api')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=['run', 'stage_key', 'shard_index', 'attempt'],
                name='uq_stage_attempt',
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                name='pipelines_stageexecution_status_valid',
                condition=models.Q(status__in=StageStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        shard = f'[{self.shard_index}]' if self.shard_index is not None else ''
        return f'{self.stage_key}{shard} attempt={self.attempt} ({self.status})'


class CostRecord(UUIDModel, TimeStampedModel):
    """Provider billing record attached to a StageExecution."""

    stage_execution = models.ForeignKey(
        StageExecution,
        on_delete=models.CASCADE,
        related_name='costs',
    )
    provider = models.CharField(max_length=32)
    operation = models.CharField(max_length=64)
    units = models.DecimalField(max_digits=12, decimal_places=4)
    unit_cost_usd = models.DecimalField(max_digits=10, decimal_places=6)
    total_usd = models.DecimalField(max_digits=10, decimal_places=4)

    @override
    def __str__(self) -> str:
        return f'{self.provider}/{self.operation} ${self.total_usd}'


class RunCast(UUIDModel):
    """Character cast assignment for a PipelineRun."""

    run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name='cast',
    )
    character = models.ForeignKey(
        'channels.Character',
        on_delete=models.PROTECT,
        related_name='+',
    )
    role = models.CharField(max_length=60)
    is_ephemeral = models.BooleanField(default=False)
    design_status = models.CharField(
        max_length=10,
        choices=CastDesignStatus.choices,
        default=CastDesignStatus.PROPOSED,
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='pipelines_runcast_design_status_valid',
                condition=models.Q(design_status__in=CastDesignStatus.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.character.name} as {self.role}'
