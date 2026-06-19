"""DMR controllers for analytics read endpoints."""

from typing import final

from dmr import Controller
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.analytics import selectors
from server.apps.analytics.logic.value_objects import (
    ChannelRoiPayload,
    RunCostPayload,
    StagePerformanceListPayload,
    StagePerformancePayload,
)
from server.apps.core.auth import JWTAuthenticatedMixin, jwt_sync_auth
from server.common.di import HasContainer


@final
class RunCostController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return cost breakdown for a single pipeline run."""

    auth = (jwt_sync_auth,)

    def get(self) -> RunCostPayload:
        """Return run cost breakdown."""
        data = selectors.get_run_cost_breakdown(str(self.kwargs['run_id']))
        return RunCostPayload(
            run_id=str(data['run_id']),
            grand_total_usd=str(data['grand_total_usd']),
            by_stage=dict(data['by_stage']),  # type: ignore[arg-type]
            by_provider=dict(data['by_provider']),  # type: ignore[arg-type]
        )


@final
class ChannelRoiController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return channel-level ROI aggregates."""

    auth = (jwt_sync_auth,)

    def get(self) -> ChannelRoiPayload:
        """Return channel ROI."""
        data = selectors.get_channel_roi(str(self.kwargs['channel_id']))
        return ChannelRoiPayload(
            channel_id=str(data['channel_id']),
            channel_name=(
                str(data['channel_name'])
                if data.get('channel_name') is not None
                else None
            ),
            run_count=int(data['run_count']),  # type: ignore[arg-type]
            completed_count=int(data['completed_count']),  # type: ignore[arg-type]
            total_spend_usd=str(data['total_spend_usd']),
            avg_cost_usd=(
                str(data['avg_cost_usd'])
                if data.get('avg_cost_usd') is not None
                else None
            ),
        )


@final
class ChannelStagesController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return per-stage performance metrics for a channel."""

    auth = (jwt_sync_auth,)

    def get(self) -> StagePerformanceListPayload:
        """Return stage performance rows."""
        rows = selectors.get_stage_performance(str(self.kwargs['channel_id']))
        return StagePerformanceListPayload(
            stage_performance=[
                StagePerformancePayload(
                    stage_key=str(row['stage_key']),
                    execution_count=int(row['execution_count']),
                    avg_duration_s=(
                        float(row['avg_duration_s'])
                        if row.get('avg_duration_s') is not None
                        else None
                    ),
                    total_cost_usd=str(row['total_cost_usd']),
                    avg_cost_per_execution_usd=(
                        str(row['avg_cost_per_execution_usd'])
                        if row.get('avg_cost_per_execution_usd') is not None
                        else None
                    ),
                )
                for row in rows
            ],
        )
