import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections  # noqa: PLC0415
        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


def test_register_stage_adds_to_registry() -> None:
    from server.apps.pipelines.stages.base import (
        STAGE_REGISTRY,
        Stage,
        register_stage,
    )

    @register_stage
    class _TestStage(Stage):
        key = '_test_register_stage'
        queue = 'api'

        async def run(self, ctx):  # type: ignore[override]
            return {}

    assert '_test_register_stage' in STAGE_REGISTRY
    assert STAGE_REGISTRY['_test_register_stage'] is _TestStage


def test_compute_input_hash_is_deterministic() -> None:
    from server.apps.pipelines.stages.base import compute_input_hash

    h1 = compute_input_hash({'a': 1, 'b': [2, 3]})
    h2 = compute_input_hash({'b': [2, 3], 'a': 1})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_cost_recorder_accumulates_total() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.pipelines.services.cost_recorder import CostRecorder

    mock_exec = MagicMock()
    mock_exec.id = 'test-id'
    recorder = CostRecorder(mock_exec)

    async def _inner():
        with patch(
            'server.apps.pipelines.models.CostRecord',
        ) as MockCostRecord:
            MockCostRecord.objects.acreate = AsyncMock()
            await recorder.record('fal_flux', 'image_gen', 1, 0.025)
            await recorder.record('fal_flux', 'image_gen', 2, 0.025)

        from decimal import Decimal
        assert recorder.total_usd == Decimal('0.075')

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_dummy_stages_registered() -> None:
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'dummy_a' in STAGE_REGISTRY
    assert 'dummy_b' in STAGE_REGISTRY
    assert 'dummy_c' in STAGE_REGISTRY


from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    return PipelineBlueprint.objects.create(
        name='idempotency_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [
            {'key': 'outline', 'depends_on': [], 'queue': 'api'},
        ]},
    )


@pytest.fixture
def channel():
    from server.apps.channels.models import Channel, ChannelKind
    return Channel.objects.create(
        name='Idempotency Channel', kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel) -> PipelineRun:
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Idempotency test topic',
    )


@pytest.mark.django_db(transaction=True)
def test_find_cached_output_returns_none_when_no_match(
    run: PipelineRun,
) -> None:
    from server.apps.pipelines.services.idempotency import find_cached_output

    async def _inner() -> None:
        result = await find_cached_output(
            stage_key='outline',
            shard_index=None,
            input_hash='nonexistent_hash',
        )
        assert result is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_find_cached_output_returns_succeeded_execution(
    run: PipelineRun,
) -> None:
    from server.apps.pipelines.models import StageExecution, StageStatus
    from server.apps.pipelines.services.idempotency import find_cached_output

    async def _inner() -> None:
        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='outline',
            input_hash='hash_abc',
            status=StageStatus.SUCCEEDED,
            output={'data': 'some_output'},
        )
        found = await find_cached_output(
            stage_key='outline',
            shard_index=None,
            input_hash='hash_abc',
        )
        assert found is not None
        assert found.id == exec_.id

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_find_cached_output_ignores_failed_executions(
    run: PipelineRun,
) -> None:
    from server.apps.pipelines.models import StageExecution, StageStatus
    from server.apps.pipelines.services.idempotency import find_cached_output

    async def _inner() -> None:
        await StageExecution.objects.acreate(
            run=run,
            stage_key='outline',
            input_hash='hash_xyz',
            status=StageStatus.FAILED,
            output={},
        )
        result = await find_cached_output(
            stage_key='outline',
            shard_index=None,
            input_hash='hash_xyz',
        )
        assert result is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_build_context_resolves_upstream(run: PipelineRun) -> None:
    # Use a blueprint with a dependency
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import build_context

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='ctx_test_v1',
            kind=PipelineKind.LONGFORM,
            graph={'stages': [
                {'key': 'step_a', 'depends_on': [], 'queue': 'api'},
                {
                    'key': 'step_b',
                    'depends_on': ['step_a'],
                    'queue': 'api',
                    'config': {'foo': 'bar'},
                },
            ]},
        )
        ch = await Channel.objects.acreate(
            name='ctx_ch', kind=ChannelKind.LONGFORM,
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='ctx test',
        )
        # Create a SUCCEEDED step_a
        await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='step_a',
            status=StageStatus.SUCCEEDED,
            output={'x': 42},
            input_hash='',
        )
        exec_b = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='step_b',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(exec_b)
        assert ctx.upstream == {'step_a': {'x': 42}}
        assert ctx.config == {'foo': 'bar'}
        assert ctx.channel.name == 'ctx_ch'

    _run(_inner())


from server.apps.pipelines.models import (  # noqa: E402 — after module imports
    RunStatus,
)


@pytest.fixture
def dummy_blueprint() -> PipelineBlueprint:
    """A 2-stage blueprint: dummy_a -> dummy_b."""
    return PipelineBlueprint.objects.create(
        name='dummy_orch_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [
            {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
            {'key': 'dummy_b', 'depends_on': ['dummy_a'], 'queue': 'api'},
        ]},
    )


@pytest.fixture
def orch_channel():
    """A test channel for orchestrator tests."""
    from server.apps.channels.models import Channel, ChannelKind  # noqa: PLC0415

    return Channel.objects.create(
        name='Orch Channel', kind=ChannelKind.LONGFORM
    )


@pytest.fixture
def orch_run(dummy_blueprint: PipelineBlueprint, orch_channel) -> PipelineRun:
    """A pipeline run using the dummy orchestrator blueprint."""
    return PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=dummy_blueprint,
        blueprint_snapshot=dummy_blueprint.graph,
        topic='Orchestrator test',
    )


@pytest.mark.django_db(transaction=True)
def test_advance_enqueues_first_stage(orch_run: PipelineRun) -> None:
    """advance_pipeline_impl enqueues dummy_a but NOT dummy_b initially."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.pipelines.models import StageExecution, StageStatus
    from server.apps.pipelines.services.orchestrator import advance_pipeline_impl

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(orch_run.id))

        executions = [e async for e in StageExecution.objects.filter(run=orch_run)]
        keys = {e.stage_key for e in executions}
        assert 'dummy_a' in keys
        assert 'dummy_b' not in keys
        a_exec = next(e for e in executions if e.stage_key == 'dummy_a')
        assert a_exec.status == StageStatus.QUEUED

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_marks_run_completed_when_all_stages_succeed(
    orch_run: PipelineRun,
) -> None:
    """When all stages SUCCEEDED, run transitions to COMPLETED."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.pipelines.models import StageExecution, StageStatus
    from server.apps.pipelines.services.orchestrator import advance_pipeline_impl

    async def _inner() -> None:
        for key in ('dummy_a', 'dummy_b'):
            await StageExecution.objects.acreate(
                run=orch_run,
                stage_key=key,
                status=StageStatus.SUCCEEDED,
                input_hash='',
            )
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(orch_run.id))

        refreshed = await PipelineRun.objects.aget(id=orch_run.id)
        assert refreshed.status == RunStatus.COMPLETED
        assert refreshed.finished_at is not None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_skips_unarmed_gate(orch_channel) -> None:
    """A gate stage not in channel.gates is skipped."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import advance_pipeline_impl

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='gated_v1',
            kind=PipelineKind.LONGFORM,
            graph={'stages': [
                {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
                {'key': 'my_gate', 'depends_on': ['dummy_a'], 'gate': True},
                {'key': 'dummy_b', 'depends_on': ['my_gate'], 'queue': 'api'},
            ]},
        )
        ch = await Channel.objects.acreate(
            name='gated_ch', kind=ChannelKind.LONGFORM
        )
        gated_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='Gate test',
        )
        await StageExecution.objects.acreate(
            run=gated_run,
            stage_key='dummy_a',
            status=StageStatus.SUCCEEDED,
            input_hash='',
        )
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(gated_run.id))

        gate_exec = await StageExecution.objects.filter(
            run=gated_run, stage_key='my_gate'
        ).afirst()
        assert gate_exec is not None
        assert gate_exec.status == StageStatus.SKIPPED

    _run(_inner())
