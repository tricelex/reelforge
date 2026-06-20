"""API DTOs for analytics."""

import msgspec


class RunCostPayload(msgspec.Struct, frozen=True):
    """Cost breakdown for a pipeline run."""

    run_id: str
    grand_total_usd: str
    by_stage: dict[str, str]
    by_provider: dict[str, str]
    lines: list['CostLinePayload']


class CostLinePayload(msgspec.Struct, frozen=True):
    """One provider cost row."""

    stage_key: str
    provider: str
    operation: str
    units: str
    unit_cost_usd: str
    total_usd: str


class ChannelRoiPayload(msgspec.Struct, frozen=True):
    """Channel-level ROI summary."""

    channel_id: str
    run_count: int
    completed_count: int
    total_spend_usd: str
    avg_cost_usd: str | None
    channel_name: str | None = None


class StagePerformancePayload(msgspec.Struct, frozen=True):
    """Per-stage performance metrics."""

    stage_key: str
    execution_count: int
    avg_duration_s: float | None
    total_cost_usd: str
    avg_cost_per_execution_usd: str | None


class StagePerformanceListPayload(msgspec.Struct, frozen=True):
    """List of stage performance rows."""

    stage_performance: list[StagePerformancePayload]


class PublishCalendarItemPayload(msgspec.Struct, frozen=True):
    """Scheduled publish job for the operator dashboard."""

    run_id: str
    channel_id: str
    channel_name: str
    schedule_at: str
    status: str


class DashboardPayload(msgspec.Struct, frozen=True):
    """Operator dashboard aggregates."""

    runs_in_flight: int
    gates_waiting: int
    spend_today_usd: str
    publish_scheduled: list[PublishCalendarItemPayload]


class DailySpendPayload(msgspec.Struct, frozen=True):
    """Spend on one calendar day."""

    date: str
    amount_usd: str


class CostSharePayload(msgspec.Struct, frozen=True):
    """Cost share slice."""

    label: str
    amount_usd: str
    pct: str


class ProviderSpendPayload(msgspec.Struct, frozen=True):
    """Spend grouped by provider."""

    provider: str
    amount_usd: str


class KpiPayload(msgspec.Struct, frozen=True):
    """Named KPI metric."""

    key: str
    label: str
    value: str


class AnalyticsSummaryPayload(msgspec.Struct, frozen=True):
    """Cross-channel analytics summary."""

    total_spend_usd: str
    daily_spend: list[DailySpendPayload]
    cost_share: list[CostSharePayload]
    providers: list[ProviderSpendPayload]
    kpis: list[KpiPayload]
