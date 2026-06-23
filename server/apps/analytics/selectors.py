"""Read-only queries for analytics data."""

from decimal import Decimal
from uuid import UUID


def get_run_cost_breakdown(run_id: str) -> dict[str, object]:
    """Cost breakdown for one run — aggregated live from CostRecord rows."""
    from django.db.models import Sum  # noqa: PLC0415

    from server.apps.pipelines.models import CostRecord  # noqa: PLC0415

    line_qs = (
        CostRecord.objects
        .filter(
            stage_execution__run_id=UUID(run_id),
            stage_execution__parent=None,
        )
        .select_related('stage_execution')
        .order_by('stage_execution__stage_key', 'provider')
    )
    lines = [
        {
            'stage_key': row.stage_execution.stage_key,
            'provider': row.provider,
            'operation': row.operation,
            'units': f'{row.units:.4f}',
            'unit_cost_usd': f'{row.unit_cost_usd:.6f}',
            'total_usd': f'{row.total_usd:.4f}',
        }
        for row in line_qs
    ]

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
        'lines': lines,
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


def get_analytics_summary(
    *,
    days: int = 30,
    channel_id: str | None = None,
) -> dict[str, object]:
    """Aggregate spend metrics for the analytics dashboard."""
    import datetime as dt  # noqa: PLC0415

    import django.utils.timezone as tz  # noqa: PLC0415
    from django.db.models import Sum  # noqa: PLC0415
    from django.db.models.functions import TruncDate  # noqa: PLC0415

    from server.apps.pipelines.models import (  # noqa: PLC0415
        CostRecord,
        PipelineRun,
        RunStatus,
    )

    window_days = min(max(days, 1), 365)
    since = tz.now() - dt.timedelta(days=window_days)

    cost_qs = CostRecord.objects.filter(created_at__gte=since)
    run_qs = PipelineRun.objects.filter(created_at__gte=since)
    if channel_id:
        channel_uuid = UUID(channel_id)
        cost_qs = cost_qs.filter(stage_execution__run__channel_id=channel_uuid)
        run_qs = run_qs.filter(channel_id=channel_uuid)

    total_spend = cost_qs.aggregate(total=Sum('total_usd')).get('total')
    total_spend_dec = total_spend if total_spend is not None else Decimal(0)

    daily_rows = (
        cost_qs
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(amount=Sum('total_usd'))
        .order_by('day')
    )
    daily_spend = [
        {
            'date': row['day'].isoformat(),
            'amount_usd': f"{row['amount']:.4f}",
        }
        for row in daily_rows
        if row['day'] is not None
    ]

    stage_rows = (
        cost_qs
        .values('stage_execution__stage_key')
        .annotate(amount=Sum('total_usd'))
        .order_by('-amount')
    )
    cost_share: list[dict[str, str]] = []
    for row in stage_rows:
        amount: Decimal = row['amount'] or Decimal(0)
        pct = (
            (amount / total_spend_dec * Decimal(100))
            if total_spend_dec > 0
            else Decimal(0)
        )
        cost_share.append(
            {
                'label': str(row['stage_execution__stage_key']),
                'amount_usd': f'{amount:.4f}',
                'pct': f'{pct:.2f}',
            },
        )

    provider_rows = (
        cost_qs
        .values('provider')
        .annotate(amount=Sum('total_usd'))
        .order_by('-amount')
    )
    providers = [
        {
            'provider': str(row['provider']),
            'amount_usd': f"{row['amount']:.4f}",
        }
        for row in provider_rows
    ]

    run_count = run_qs.count()
    completed_count = run_qs.filter(status=RunStatus.COMPLETED).count()
    avg_cost = (
        total_spend_dec / Decimal(run_count) if run_count > 0 else Decimal(0)
    )
    kpis = [
        {
            'key': 'total_spend_usd',
            'label': 'Total spend',
            'value': f'{total_spend_dec:.4f}',
        },
        {
            'key': 'run_count',
            'label': 'Runs',
            'value': str(run_count),
        },
        {
            'key': 'completed_count',
            'label': 'Completed runs',
            'value': str(completed_count),
        },
        {
            'key': 'avg_cost_usd',
            'label': 'Avg cost per run',
            'value': f'{avg_cost:.4f}',
        },
    ]

    return {
        'total_spend_usd': f'{total_spend_dec:.4f}',
        'daily_spend': daily_spend,
        'cost_share': cost_share,
        'providers': providers,
        'kpis': kpis,
    }


def get_dashboard() -> dict[str, object]:
    """Return operator dashboard aggregates from live tables."""
    from decimal import Decimal  # noqa: PLC0415

    import django.utils.timezone as tz  # noqa: PLC0415
    from django.db.models import Sum  # noqa: PLC0415

    from server.apps.pipelines.gate_selectors import (  # noqa: PLC0415
        count_gates_waiting,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )
    from server.apps.publishing.models import PublishJob  # noqa: PLC0415

    in_flight_statuses = {
        RunStatus.PENDING,
        RunStatus.RUNNING,
        RunStatus.AWAITING_REVIEW,
        RunStatus.BUDGET_HOLD,
        RunStatus.PUBLISHING,
    }
    runs_in_flight = PipelineRun.objects.filter(
        status__in=in_flight_statuses,
    ).count()

    gates_waiting = count_gates_waiting()

    today = tz.localdate()
    spend_today = PipelineRun.objects.filter(created_at__date=today).aggregate(
        total=Sum('total_cost_usd'),
    ).get('total') or Decimal(0)

    publish_rows = (
        PublishJob.objects
        .filter(schedule_at__isnull=False)
        .select_related('channel', 'run')
        .order_by('schedule_at')[:20]
    )
    publish_scheduled = [
        {
            'run_id': str(row.run_id),
            'channel_id': str(row.channel_id),
            'channel_name': row.channel.name,
            'schedule_at': (
                row.schedule_at.isoformat()
                if row.schedule_at is not None  # type: ignore[comparison-overlap, redundant-expr]
                else ''
            ),
            'status': row.status,
        }
        for row in publish_rows
        if row.schedule_at is not None
    ]

    return {
        'runs_in_flight': runs_in_flight,
        'gates_waiting': gates_waiting,
        'spend_today_usd': f'{spend_today:.4f}',
        'publish_scheduled': publish_scheduled,
    }
