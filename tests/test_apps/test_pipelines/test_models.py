from decimal import Decimal

import pytest
from django.db import IntegrityError

from server.apps.pipelines.models import (
    CastDesignStatus,
    CostRecord,
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunCast,
    RunStatus,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    """Test blueprint with two stages."""
    return PipelineBlueprint.objects.create(
        name='test_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'stage_a', 'depends_on': [], 'queue': 'api'},
                {'key': 'stage_b', 'depends_on': ['stage_a'], 'queue': 'api'},
            ],
        },
    )


@pytest.fixture
def channel():
    """Test channel."""
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )

    return Channel.objects.create(
        name='Test Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(blueprint, channel) -> PipelineRun:
    """Test pipeline run."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Test video topic',
    )


@pytest.mark.django_db
def test_blueprint_defaults() -> None:
    """PipelineBlueprint defaults: is_active=True, version=1, str format."""
    bp = PipelineBlueprint.objects.create(
        name='my_bp',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    assert bp.is_active is True
    assert bp.version == 1
    assert str(bp) == 'my_bp v1'


@pytest.mark.django_db
def test_run_defaults(run: PipelineRun) -> None:
    """PipelineRun defaults: PENDING status, zero cost, no timestamps."""
    assert run.status == RunStatus.PENDING
    assert run.total_cost_usd == Decimal(0)
    assert run.started_at is None
    assert 'Run' in str(run)


@pytest.mark.django_db
def test_stage_execution_defaults(run: PipelineRun) -> None:
    """StageExecution defaults: PENDING, attempt=0, max_retries=3, queue=api."""
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='research',
        input_hash='abc123',
    )
    assert exec_.status == StageStatus.PENDING
    assert exec_.attempt == 0
    assert exec_.max_retries == 3
    assert exec_.queue == 'api'
    assert exec_.parent is None
    assert exec_.shard_index is None


@pytest.mark.django_db
def test_stage_execution_unique_constraint(run: PipelineRun) -> None:
    """uq_stage_attempt violation raises IntegrityError."""
    StageExecution.objects.create(
        run=run,
        stage_key='research',
        shard_index=None,
        attempt=0,
        input_hash='',
    )
    with pytest.raises(IntegrityError):
        StageExecution.objects.create(
            run=run,
            stage_key='research',
            shard_index=None,
            attempt=0,
            input_hash='',
        )


@pytest.mark.django_db
def test_cost_record_str(run: PipelineRun) -> None:
    """CostRecord.__str__ includes provider name."""
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        input_hash='',
    )
    cost = CostRecord.objects.create(
        stage_execution=exec_,
        provider='fal_flux',
        operation='image_gen',
        units=Decimal(1),
        unit_cost_usd=Decimal('0.025'),
        total_usd=Decimal('0.025'),
    )
    assert 'fal_flux' in str(cost)


@pytest.mark.django_db
def test_run_cast_defaults(run: PipelineRun, channel) -> None:
    """RunCast defaults: PROPOSED design_status, is_ephemeral=False."""
    from server.apps.channels.models import Character

    char = Character.objects.create(
        channel=channel,
        name='Alaric',
        appearance_prompt='tall king',
    )
    cast = RunCast.objects.create(run=run, character=char, role='protagonist')
    assert cast.design_status == CastDesignStatus.PROPOSED
    assert cast.is_ephemeral is False
