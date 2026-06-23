"""DMR controllers for analytics read endpoints."""

from typing import final

from dmr import Controller
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.analytics import selectors
from server.apps.analytics.logic.value_objects import (
    AnalyticsSummaryPayload,
    ChannelRoiPayload,
    CostLinePayload,
    CostSharePayload,
    DailySpendPayload,
    DashboardPayload,
    KpiPayload,
    ProviderSpendPayload,
    PublishCalendarItemPayload,
    RunCostPayload,
    StagePerformanceListPayload,
    StagePerformancePayload,
)
from server.common.auth import JWTAuthenticatedMixin, jwt_sync_auth
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
        lines_raw = data.get('lines', [])
        lines = (
            [
                CostLinePayload(
                    stage_key=str(row['stage_key']),
                    provider=str(row['provider']),
                    operation=str(row['operation']),
                    units=str(row['units']),
                    unit_cost_usd=str(row['unit_cost_usd']),
                    total_usd=str(row['total_usd']),
                )
                for row in lines_raw
                if isinstance(row, dict)
            ]
            if isinstance(lines_raw, list)
            else []
        )
        return RunCostPayload(
            run_id=str(data['run_id']),
            grand_total_usd=str(data['grand_total_usd']),
            by_stage=dict(data['by_stage']),  # type: ignore[call-overload]
            by_provider=dict(data['by_provider']),  # type: ignore[call-overload]
            lines=lines,
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
            run_count=int(data['run_count']),  # type: ignore[call-overload]
            completed_count=int(data['completed_count']),  # type: ignore[call-overload]
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
                    execution_count=int(row['execution_count']),  # type: ignore[call-overload]
                    avg_duration_s=(
                        float(row['avg_duration_s'])  # type: ignore[arg-type]
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


@final
class AnalyticsSummaryController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return cross-channel analytics summary."""

    auth = (jwt_sync_auth,)

    def get(self) -> AnalyticsSummaryPayload:
        """Return spend aggregates."""
        days_raw = self.request.GET.get('days', '30')
        channel_id = self.request.GET.get('channel_id')
        try:
            days = int(days_raw)
        except ValueError:
            days = 30
        data = selectors.get_analytics_summary(
            days=days,
            channel_id=channel_id,
        )
        return AnalyticsSummaryPayload(
            total_spend_usd=str(data['total_spend_usd']),
            daily_spend=[
                DailySpendPayload(
                    date=str(row['date']),
                    amount_usd=str(row['amount_usd']),
                )
                for row in data['daily_spend']  # type: ignore[union-attr]
                if isinstance(row, dict)
            ],
            cost_share=[
                CostSharePayload(
                    label=str(row['label']),
                    amount_usd=str(row['amount_usd']),
                    pct=str(row['pct']),
                )
                for row in data['cost_share']  # type: ignore[union-attr]
                if isinstance(row, dict)
            ],
            providers=[
                ProviderSpendPayload(
                    provider=str(row['provider']),
                    amount_usd=str(row['amount_usd']),
                )
                for row in data['providers']  # type: ignore[union-attr]
                if isinstance(row, dict)
            ],
            kpis=[
                KpiPayload(
                    key=str(row['key']),
                    label=str(row['label']),
                    value=str(row['value']),
                )
                for row in data['kpis']  # type: ignore[union-attr]
                if isinstance(row, dict)
            ],
        )


@final
class DashboardController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return operator dashboard aggregates."""

    auth = (jwt_sync_auth,)

    def get(self) -> DashboardPayload:
        """Return dashboard summary."""
        data = selectors.get_dashboard()
        calendar = data['publish_scheduled']
        if not isinstance(calendar, list):
            calendar = []
        return DashboardPayload(
            runs_in_flight=int(data['runs_in_flight']),  # type: ignore[call-overload]
            gates_waiting=int(data['gates_waiting']),  # type: ignore[call-overload]
            spend_today_usd=str(data['spend_today_usd']),
            publish_scheduled=[
                PublishCalendarItemPayload(
                    run_id=str(item['run_id']),
                    channel_id=str(item['channel_id']),
                    channel_name=str(item['channel_name']),
                    schedule_at=str(item['schedule_at']),
                    status=str(item['status']),
                )
                for item in calendar
                if isinstance(item, dict)
            ],
        )
