"""Read-only queries for analytics data."""

from decimal import Decimal
from uuid import UUID


def get_run_cost_breakdown(run_id: str) -> dict[str, object]:
    """Cost breakdown for one run — aggregated live from CostRecord rows."""
    from django.db.models import Sum  # noqa: PLC0415

    from server.apps.pipelines.models import CostRecord  # noqa: PLC0415

    records = (
        CostRecord.objects
        .filter(
            stage_execution__run_id=UUID(run_id),
            stage_execution__parent=None,
        )
        .values('provider', 'stage_execution__stage_key')
        .annotate(total=Sum('total_usd'))
    )

    by_stage: dict[str, Decimal] = {}
    by_provider: dict[str, Decimal] = {}
    grand_total = Decimal('0.0000')

    for row in records:
        stage = row['stage_execution__stage_key']
        provider = row['provider']
        total: Decimal = row['total'] or Decimal(0)
        by_stage[stage] = by_stage.get(stage, Decimal(0)) + total
        by_provider[provider] = by_provider.get(provider, Decimal(0)) + total
        grand_total += total

    return {
        'run_id': run_id,
        'grand_total_usd': f'{grand_total:.4f}',
        'by_stage': {k: f'{v:.4f}' for k, v in by_stage.items()},
        'by_provider': {k: f'{v:.4f}' for k, v in by_provider.items()},
    }


def get_channel_roi(channel_id: str) -> dict[str, object]:
    """Channel-level ROI from the analytics_channel_roi materialized view."""
    from server.apps.analytics.models import ChannelRoi  # noqa: PLC0415

    try:
        row = ChannelRoi.objects.get(channel_id=UUID(channel_id))
    except ChannelRoi.DoesNotExist:
        return {
            'channel_id': channel_id,
            'run_count': 0,
            'completed_count': 0,
            'total_spend_usd': '0.0000',
            'avg_cost_usd': None,
        }
    return {
        'channel_id': channel_id,
        'channel_name': row.channel_name,
        'run_count': row.run_count,
        'completed_count': row.completed_count,
        'total_spend_usd': f'{row.total_spend_usd:.4f}',
        'avg_cost_usd': (
            f'{row.avg_cost_usd:.4f}' if row.avg_cost_usd else None
        ),
    }


def get_stage_performance(channel_id: str) -> list[dict[str, object]]:
    """Per-stage performance for a channel.

    Reads from the analytics_stage_performance materialized view.
    """
    from server.apps.analytics.models import StagePerformance  # noqa: PLC0415

    rows = StagePerformance.objects.filter(
        channel_id=UUID(channel_id),
    ).order_by('stage_key')
    return [
        {
            'stage_key': row.stage_key,
            'execution_count': row.execution_count,
            'avg_duration_s': row.avg_duration_s,
            'total_cost_usd': f'{row.total_cost_usd:.4f}',
            'avg_cost_per_execution_usd': (
                f'{row.avg_cost_per_execution_usd:.4f}'
                if row.avg_cost_per_execution_usd
                else None
            ),
        }
        for row in rows
    ]
