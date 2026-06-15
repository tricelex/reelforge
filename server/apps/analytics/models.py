"""Unmanaged Django models backed by PostgreSQL materialized views.

The views are created in migration 0001_initial. Call
``refresh_analytics_views()`` (in tasks.py) to keep them current.
"""

from django.db import models


class RunCostSummary(models.Model):
    """One row per completed or failed PipelineRun — materialized view."""

    run_id = models.UUIDField(primary_key=True)
    channel_id = models.UUIDField()
    status = models.CharField(max_length=20)
    topic = models.TextField()
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=4)
    created_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    duration_s = models.FloatField(null=True)
    cost_by_provider = models.JSONField(null=True)

    class Meta:
        managed = False
        db_table = 'analytics_run_cost_summary'


class ChannelRoi(models.Model):
    """One row per Channel — materialized view."""

    channel_id = models.UUIDField(primary_key=True)
    channel_name = models.CharField(max_length=120)
    run_count = models.IntegerField()
    completed_count = models.IntegerField()
    total_spend_usd = models.DecimalField(max_digits=12, decimal_places=4)
    avg_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, null=True
    )

    class Meta:
        managed = False
        db_table = 'analytics_channel_roi'


class StagePerformance(models.Model):
    """One row per (channel, stage_key) pair — materialized view."""

    id = models.BigAutoField(primary_key=True)
    stage_key = models.CharField(max_length=64)
    channel_id = models.UUIDField()
    execution_count = models.IntegerField()
    avg_duration_s = models.FloatField(null=True)
    total_cost_usd = models.DecimalField(max_digits=12, decimal_places=4)
    avg_cost_per_execution_usd = models.DecimalField(
        max_digits=10, decimal_places=4, null=True
    )

    class Meta:
        managed = False
        db_table = 'analytics_stage_performance'
