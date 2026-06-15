"""Tests for analytics selector functions."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from server.apps.analytics.selectors import (
    get_channel_roi,
    get_run_cost_breakdown,
    get_stage_performance,
)
from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    CostRecord,
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def channel(db):
    """Analytics test channel."""
    return Channel.objects.create(
        name='Analytics Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def blueprint(db):
    """Analytics test blueprint."""
    return PipelineBlueprint.objects.create(
        name='ana_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )


@pytest.fixture
def completed_run(channel, blueprint):
    """Completed pipeline run for analytics tests."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Analytics test',
        status=RunStatus.COMPLETED,
        total_cost_usd=Decimal('0.0750'),
    )


@pytest.fixture
def stage_exec(completed_run):
    """Succeeded stage execution for analytics tests."""
    return StageExecution.objects.create(
        run=completed_run,
        stage_key='script',
        status=StageStatus.SUCCEEDED,
        input_hash='abc',
    )


@pytest.fixture
def cost_record(stage_exec):
    """Cost record attached to stage_exec for analytics tests."""
    return CostRecord.objects.create(
        stage_execution=stage_exec,
        provider='openai',
        operation='chat_completion',
        units=Decimal(1000),
        unit_cost_usd=Decimal('0.000005'),
        total_usd=Decimal('0.0050'),
    )


@pytest.mark.django_db
def test_get_run_cost_breakdown_returns_dict(completed_run, cost_record):
    """get_run_cost_breakdown returns a dict with required keys."""
    result = get_run_cost_breakdown(str(completed_run.id))
    assert result['run_id'] == str(completed_run.id)
    assert 'grand_total_usd' in result
    assert 'by_stage' in result
    assert 'by_provider' in result


@pytest.mark.django_db
def test_get_run_cost_breakdown_aggregates_by_provider(
    completed_run,
    cost_record,
):
    """get_run_cost_breakdown aggregates totals by provider name."""
    result = get_run_cost_breakdown(str(completed_run.id))
    assert 'openai' in result['by_provider']
    assert result['by_provider']['openai'] == '0.0050'


@pytest.mark.django_db
def test_get_run_cost_breakdown_aggregates_by_stage(completed_run, cost_record):
    """get_run_cost_breakdown groups spend by stage key."""
    result = get_run_cost_breakdown(str(completed_run.id))
    assert 'script' in result['by_stage']


@pytest.mark.django_db
def test_get_run_cost_breakdown_empty_run(completed_run):
    """get_run_cost_breakdown returns zeros for a run with no cost records."""
    result = get_run_cost_breakdown(str(completed_run.id))
    assert result['grand_total_usd'] == '0.0000'
    assert result['by_stage'] == {}
    assert result['by_provider'] == {}


def test_get_channel_roi_with_existing_row() -> None:
    """get_channel_roi returns row data when a ChannelRoi record is found."""
    channel_id = 'aaaaaaaa-0000-0000-0000-000000000001'
    mock_row = MagicMock()
    mock_row.channel_name = 'Test Channel'
    mock_row.run_count = 5
    mock_row.completed_count = 4
    mock_row.total_spend_usd = Decimal('12.5000')
    mock_row.avg_cost_usd = Decimal('2.5000')

    with patch('server.apps.analytics.models.ChannelRoi') as mock_cls:
        mock_cls.objects.get.return_value = mock_row
        mock_cls.DoesNotExist = Exception
        result = get_channel_roi(channel_id)

    assert result['channel_id'] == channel_id
    assert result['channel_name'] == 'Test Channel'
    assert result['run_count'] == 5
    assert result['completed_count'] == 4
    assert result['total_spend_usd'] == '12.5000'
    assert result['avg_cost_usd'] == '2.5000'


def test_get_channel_roi_avg_cost_none() -> None:
    """get_channel_roi returns None for avg_cost_usd when it is null."""
    channel_id = 'aaaaaaaa-0000-0000-0000-000000000002'
    mock_row = MagicMock()
    mock_row.channel_name = 'Empty Channel'
    mock_row.run_count = 1
    mock_row.completed_count = 0
    mock_row.total_spend_usd = Decimal('0.0000')
    mock_row.avg_cost_usd = None

    with patch('server.apps.analytics.models.ChannelRoi') as mock_cls:
        mock_cls.objects.get.return_value = mock_row
        mock_cls.DoesNotExist = Exception
        result = get_channel_roi(channel_id)

    assert result['avg_cost_usd'] is None


def test_get_stage_performance_returns_list() -> None:
    """get_stage_performance returns a list of per-stage dicts."""
    channel_id = 'aaaaaaaa-0000-0000-0000-000000000003'

    mock_row = MagicMock()
    mock_row.stage_key = 'research'
    mock_row.execution_count = 3
    mock_row.avg_duration_s = 1.5
    mock_row.total_cost_usd = Decimal('0.0150')
    mock_row.avg_cost_per_execution_usd = Decimal('0.0050')

    with patch('server.apps.analytics.models.StagePerformance') as mock_cls:
        mock_cls.objects.filter.return_value.order_by.return_value = [mock_row]
        rows = get_stage_performance(channel_id)

    assert len(rows) == 1
    assert rows[0]['stage_key'] == 'research'
    assert rows[0]['execution_count'] == 3
    assert rows[0]['total_cost_usd'] == '0.0150'
    assert rows[0]['avg_cost_per_execution_usd'] == '0.0050'


def test_get_stage_performance_avg_cost_per_exec_none() -> None:
    """get_stage_performance returns None for avg_cost_per_execution_usd.

    Covers the falsy branch in the avg_cost_per_execution_usd ternary.
    """
    channel_id = 'aaaaaaaa-0000-0000-0000-000000000004'

    mock_row = MagicMock()
    mock_row.stage_key = 'script'
    mock_row.execution_count = 0
    mock_row.avg_duration_s = None
    mock_row.total_cost_usd = Decimal('0.0000')
    mock_row.avg_cost_per_execution_usd = None

    with patch('server.apps.analytics.models.StagePerformance') as mock_cls:
        mock_cls.objects.filter.return_value.order_by.return_value = [mock_row]
        rows = get_stage_performance(channel_id)

    assert rows[0]['avg_cost_per_execution_usd'] is None
