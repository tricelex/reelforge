"""API DTOs for analytics."""

import msgspec


class RunCostPayload(msgspec.Struct, frozen=True):
    """Cost breakdown for a pipeline run."""

    run_id: str
    grand_total_usd: str
    by_stage: dict[str, str]
    by_provider: dict[str, str]


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
