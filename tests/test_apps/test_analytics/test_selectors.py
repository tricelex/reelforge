from decimal import Decimal

import pytest

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
from server.apps.analytics.selectors import get_run_cost_breakdown


@pytest.fixture
def channel(db):
    return Channel.objects.create(name='Analytics Channel', kind=ChannelKind.LONGFORM)


@pytest.fixture
def blueprint(db):
    return PipelineBlueprint.objects.create(
        name='ana_v1', kind=PipelineKind.LONGFORM, graph={'stages': []}
    )


@pytest.fixture
def completed_run(channel, blueprint):
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
    return StageExecution.objects.create(
        run=completed_run,
        stage_key='script',
        status=StageStatus.SUCCEEDED,
        input_hash='abc',
    )


@pytest.fixture
def cost_record(stage_exec):
    return CostRecord.objects.create(
        stage_execution=stage_exec,
        provider='openai',
        operation='chat_completion',
        units=Decimal('1000'),
        unit_cost_usd=Decimal('0.000005'),
        total_usd=Decimal('0.0050'),
    )


@pytest.mark.django_db
def test_get_run_cost_breakdown_returns_dict(completed_run, cost_record):
    result = get_run_cost_breakdown(str(completed_run.id))
    assert result['run_id'] == str(completed_run.id)
    assert 'grand_total_usd' in result
    assert 'by_stage' in result
    assert 'by_provider' in result


@pytest.mark.django_db
def test_get_run_cost_breakdown_aggregates_by_provider(completed_run, cost_record):
    result = get_run_cost_breakdown(str(completed_run.id))
    assert 'openai' in result['by_provider']
    assert result['by_provider']['openai'] == '0.0050'


@pytest.mark.django_db
def test_get_run_cost_breakdown_aggregates_by_stage(completed_run, cost_record):
    result = get_run_cost_breakdown(str(completed_run.id))
    assert 'script' in result['by_stage']


@pytest.mark.django_db
def test_get_run_cost_breakdown_empty_run(completed_run):
    result = get_run_cost_breakdown(str(completed_run.id))
    assert result['grand_total_usd'] == '0.0000'
    assert result['by_stage'] == {}
    assert result['by_provider'] == {}
