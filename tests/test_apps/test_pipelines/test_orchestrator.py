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
    """Decorated stage class appears in STAGE_REGISTRY under its key."""
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
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
    assert asyncio.run(_TestStage().run(None)) == {}


def test_compute_input_hash_is_deterministic() -> None:
    """Input hash is stable regardless of key insertion order."""
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        compute_input_hash,
    )

    h1 = compute_input_hash({'a': 1, 'b': [2, 3]})
    h2 = compute_input_hash({'b': [2, 3], 'a': 1})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_cost_recorder_accumulates_total() -> None:
    """CostRecorder sums multiple record() calls into total_usd."""
    from unittest.mock import AsyncMock, MagicMock, patch  # noqa: PLC0415

    from server.apps.pipelines.services.cost_recorder import (  # noqa: PLC0415
        CostRecorder,
    )

    mock_exec = MagicMock()
    mock_exec.id = 'test-id'
    recorder = CostRecorder(mock_exec)

    async def _inner():
        with patch(
            'server.apps.pipelines.models.CostRecord',
        ) as mock_cost_record_cls:
            mock_cost_record_cls.objects.acreate = AsyncMock()
            await recorder.record('fal_flux', 'image_gen', 1, 0.025)
            await recorder.record('fal_flux', 'image_gen', 2, 0.025)

        from decimal import Decimal  # noqa: PLC0415

        assert recorder.total_usd == Decimal('0.075')

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_dummy_stages_registered() -> None:
    """Importing dummy module populates STAGE_REGISTRY with a/b/c keys."""
    import server.apps.pipelines.stages.dummy  # noqa: F401, PLC0415
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
    )

    assert 'dummy_a' in STAGE_REGISTRY
    assert 'dummy_b' in STAGE_REGISTRY
    assert 'dummy_c' in STAGE_REGISTRY


from server.apps.pipelines.models import (  # noqa: E402
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    """Blueprint with a single outline stage for idempotency tests."""
    return PipelineBlueprint.objects.create(
        name='idempotency_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'outline', 'depends_on': [], 'queue': 'api'},
            ],
        },
    )


@pytest.fixture
def channel():
    """Test channel for idempotency tests."""
    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )

    return Channel.objects.create(
        name='Idempotency Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel) -> PipelineRun:
    """Pipeline run for idempotency tests."""
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
    """find_cached_output returns None when no SUCCEEDED exec matches."""
    from server.apps.pipelines.services.idempotency import (  # noqa: PLC0415
        find_cached_output,
    )

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
    """find_cached_output returns a SUCCEEDED execution with matching hash."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.idempotency import (  # noqa: PLC0415
        find_cached_output,
    )

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
    """find_cached_output does not return FAILED executions."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.idempotency import (  # noqa: PLC0415
        find_cached_output,
    )

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
    """build_context gives empty upstream when dep has no SUCCEEDED exec."""
    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import (  # noqa: PLC0415
        build_context,
    )

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='ctx_test_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'step_a', 'depends_on': [], 'queue': 'api'},
                    {
                        'key': 'step_b',
                        'depends_on': ['step_a'],
                        'queue': 'api',
                        'config': {'foo': 'bar'},
                    },
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='ctx_ch',
            kind=ChannelKind.LONGFORM,
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='ctx test',
        )
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


from server.apps.pipelines.models import (  # noqa: E402
    RunStatus,
)


@pytest.fixture
def dummy_blueprint() -> PipelineBlueprint:
    """A 2-stage blueprint: dummy_a -> dummy_b."""
    return PipelineBlueprint.objects.create(
        name='dummy_orch_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
                {'key': 'dummy_b', 'depends_on': ['dummy_a'], 'queue': 'api'},
            ],
        },
    )


@pytest.fixture
def orch_channel():
    """A test channel for orchestrator tests."""
    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )

    return Channel.objects.create(
        name='Orch Channel',
        kind=ChannelKind.LONGFORM,
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
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    import server.apps.pipelines.stages.dummy  # noqa: F401, PLC0415
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

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

        executions = [
            e async for e in StageExecution.objects.filter(run=orch_run)
        ]
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

    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

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

    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='gated_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
                    {'key': 'my_gate', 'depends_on': ['dummy_a'], 'gate': True},
                    {
                        'key': 'dummy_b',
                        'depends_on': ['my_gate'],
                        'queue': 'api',
                    },
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='gated_ch',
            kind=ChannelKind.LONGFORM,
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
            run=gated_run,
            stage_key='my_gate',
        ).afirst()
        assert gate_exec is not None
        assert gate_exec.status == StageStatus.SKIPPED

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_parks_run_at_awaiting_review_for_armed_gate():
    """An armed gate sets run.status=AWAITING_REVIEW and creates a RUNNING execution."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    channel = Channel.objects.create(
        name='Gate Channel',
        kind=ChannelKind.LONGFORM,
        gates=['final_gate'],  # gate is armed
    )
    bp = PipelineBlueprint.objects.create(
        name='gate_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {
                    'key': 'final_gate',
                    'depends_on': [],
                    'gate': True,
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='gate test',
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
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
        _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    assert run.status == RunStatus.AWAITING_REVIEW
    exec_ = StageExecution.objects.get(run=run, stage_key='final_gate')
    assert exec_.status == StageStatus.RUNNING


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_skips_unarmed_gate():
    """A gate NOT in channel.gates is auto-skipped."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )

    channel = Channel.objects.create(
        name='No Gate Channel',
        kind=ChannelKind.LONGFORM,
        gates=[],  # gate NOT armed
    )
    bp = PipelineBlueprint.objects.create(
        name='gate_skip_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {
                    'key': 'final_gate',
                    'depends_on': [],
                    'gate': True,
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='skip gate test',
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
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
        _run(advance_pipeline_impl(str(run.id)))

    exec_ = StageExecution.objects.get(run=run, stage_key='final_gate')
    assert exec_.status == StageStatus.SKIPPED


@pytest.mark.django_db(transaction=True)
def test_approve_gate_marks_succeeded_and_resumes():
    """approve_gate_impl marks the gate SUCCEEDED and sets run back to RUNNING."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    channel = Channel.objects.create(
        name='Approve Channel',
        kind=ChannelKind.LONGFORM,
        gates=['final_gate'],
    )
    bp = PipelineBlueprint.objects.create(
        name='approve_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {
                    'key': 'final_gate',
                    'depends_on': [],
                    'gate': True,
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='approve test',
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
        approve_gate_impl,
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
        _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    assert run.status == RunStatus.AWAITING_REVIEW

    output = {'approved': True, 'thumbnail_asset_id': None}
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
        _run(approve_gate_impl(str(run.id), 'final_gate', output))

    run.refresh_from_db()
    assert run.status in {RunStatus.RUNNING, RunStatus.COMPLETED}
    exec_ = StageExecution.objects.get(run=run, stage_key='final_gate')
    assert exec_.status == StageStatus.SUCCEEDED
    assert exec_.output == output


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_armed_gate_with_unfinished_deps_is_not_parked():
    """An armed gate with unfinished deps is not parked (branch 195->198)."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from server.apps.channels.models import (  # noqa: PLC0415
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    channel = Channel.objects.create(
        name='Gate Pending Channel',
        kind=ChannelKind.LONGFORM,
        gates=['final_gate'],  # gate is armed
    )
    bp = PipelineBlueprint.objects.create(
        name='gate_pending_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                # dep_stage is not yet succeeded
                {'key': 'dep_stage', 'depends_on': [], 'queue': 'api'},
                {
                    'key': 'final_gate',
                    'depends_on': ['dep_stage'],
                    'gate': True,
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='gate pending test',
    )
    # Mark dep_stage as RUNNING (not terminal) so the gate dep check fails
    StageExecution.objects.create(
        run=run,
        stage_key='dep_stage',
        status=StageStatus.RUNNING,
        output={},
    )

    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
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
        _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    # Run should not be parked at AWAITING_REVIEW since dep is still running
    assert run.status != RunStatus.AWAITING_REVIEW
    # The gate execution should not be created
    assert not StageExecution.objects.filter(
        run=run, stage_key='final_gate',
    ).exists()
