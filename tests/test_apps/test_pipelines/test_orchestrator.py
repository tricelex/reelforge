import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


def test_register_stage_adds_to_registry() -> None:
    """Decorated stage class appears in STAGE_REGISTRY under its key."""
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
    assert asyncio.run(_TestStage().run(None)) == {}


def test_compute_input_hash_is_deterministic() -> None:
    """Input hash is stable regardless of key insertion order."""
    from server.apps.pipelines.stages.base import (
        compute_input_hash,
    )

    h1 = compute_input_hash({'a': 1, 'b': [2, 3]})
    h2 = compute_input_hash({'b': [2, 3], 'a': 1})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_cost_recorder_accumulates_total() -> None:
    """CostRecorder sums multiple record() calls into total_usd."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.pipelines.services.cost_recorder import (
        CostRecorder,
    )

    mock_exec = MagicMock()
    mock_exec.id = 'test-id'
    mock_exec.run_id = 'test-run-id'
    recorder = CostRecorder(mock_exec)

    async def _inner():
        with (
            patch(
                'server.apps.pipelines.models.CostRecord',
            ) as mock_cost_record_cls,
            patch(
                'server.apps.pipelines.models.PipelineRun',
            ) as mock_run_cls,
        ):
            mock_cost_record_cls.objects.acreate = AsyncMock()
            mock_run_cls.objects.filter.return_value.aupdate = AsyncMock()
            await recorder.record('fal_flux', 'image_gen', 1, 0.025)
            await recorder.record('fal_flux', 'image_gen', 2, 0.025)

        from decimal import Decimal

        assert recorder.total_usd == Decimal('0.075')
        assert mock_run_cls.objects.filter.call_count == 2
        mock_run_cls.objects.filter.assert_any_call(id='test-run-id')

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_cost_recorder_rolls_up_onto_pipeline_run() -> None:
    """CostRecorder.record() atomically adds cost onto PipelineRun.total_cost_usd.

    Regression: PipelineRun.total_cost_usd was write-only-by-default — it
    is displayed to operators (gate queue "spent so far", run detail API)
    but nothing ever summed CostRecord entries back onto it, so it always
    read $0.00 regardless of actual spend.
    """
    from decimal import Decimal

    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
    )
    from server.apps.pipelines.services.cost_recorder import CostRecorder

    channel = Channel.objects.create(
        name='Cost Rollup Channel',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='cost_rollup_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'dummy_a', 'depends_on': []}]},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='cost rollup test',
    )
    execution = StageExecution.objects.create(
        run=run,
        stage_key='dummy_a',
        input_hash='',
    )
    recorder = CostRecorder(execution)

    async def _inner() -> None:
        await recorder.record('fal_flux', 'image_gen', 2, 0.025)
        await recorder.record('elevenlabs', 'tts_chars', 100, 0.00003)

    _run(_inner())

    run.refresh_from_db()
    assert run.total_cost_usd == Decimal('0.0530')


@pytest.mark.django_db(transaction=True)
def test_dummy_stages_registered() -> None:
    """Importing dummy module populates STAGE_REGISTRY with a/b/c keys."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.stages.base import (
        STAGE_REGISTRY,
    )

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
    from server.apps.channels.models import (
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
    from server.apps.pipelines.services.idempotency import (
        find_cached_output,
    )

    async def _inner() -> None:
        result = await find_cached_output(
            run_id=run.id,
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
    from server.apps.pipelines.models import (
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.idempotency import (
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
            run_id=run.id,
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
    from server.apps.pipelines.models import (
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.idempotency import (
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
            run_id=run.id,
            stage_key='outline',
            shard_index=None,
            input_hash='hash_xyz',
        )
        assert result is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_find_cached_output_does_not_leak_across_runs(
    run: PipelineRun,
    blueprint: PipelineBlueprint,
    channel,
) -> None:
    """A SUCCEEDED execution on another run must never be returned as cache.

    Regression test: the cache used to be keyed only on
    (stage_key, shard_index, input_hash) with no run/channel scoping, so two
    different runs (potentially different channels, different niches/lore)
    that happened to hash identically would silently share output.
    """
    from server.apps.pipelines.models import (
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.idempotency import (
        find_cached_output,
    )

    other_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Idempotency test topic',
    )

    async def _inner() -> None:
        await StageExecution.objects.acreate(
            run=other_run,
            stage_key='outline',
            input_hash='shared_hash',
            status=StageStatus.SUCCEEDED,
            output={'data': 'other_run_output'},
        )
        result = await find_cached_output(
            run_id=run.id,
            stage_key='outline',
            shard_index=None,
            input_hash='shared_hash',
        )
        assert result is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_build_context_resolves_upstream(run: PipelineRun) -> None:
    """build_context gives empty upstream when dep has no SUCCEEDED exec."""
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import (
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


@pytest.mark.django_db(transaction=True)
def test_build_context_resolves_transitive_upstream() -> None:
    """build_context includes outputs from transitive depends_on ancestors."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import build_context

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='ctx_transitive_v1',
            kind=PipelineKind.CLIPPING,
            graph={
                'stages': [
                    {'key': 'clip_ingest', 'depends_on': []},
                    {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
                    {
                        'key': 'clip_analyze',
                        'depends_on': ['clip_transcribe'],
                    },
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='ctx_transitive_ch',
            kind=ChannelKind.CLIPPING,
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='transitive ctx test',
        )
        await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='clip_ingest',
            status=StageStatus.SUCCEEDED,
            output={'asset_id': 'ingest-asset-id'},
            input_hash='',
        )
        await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='clip_transcribe',
            status=StageStatus.SUCCEEDED,
            output={'manifest_asset_id': 'manifest-id'},
            input_hash='',
        )
        exec_analyze = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='clip_analyze',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(exec_analyze)
        assert ctx.upstream == {
            'clip_transcribe': {'manifest_asset_id': 'manifest-id'},
            'clip_ingest': {'asset_id': 'ingest-asset-id'},
        }

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_build_context_merges_channel_config_overrides() -> None:
    """build_context merges channel config_overrides over blueprint config."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import build_context

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='override_ctx_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {
                        'key': 'motion',
                        'depends_on': [],
                        'queue': 'render',
                        'config': {'hero_ratio': 0.15},
                    },
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='override_ch',
            kind=ChannelKind.LONGFORM,
            config_overrides={'motion': {'hero_ratio': 0.2}},
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='override test',
        )
        execution = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='motion',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(execution)
        assert ctx.config == {'hero_ratio': 0.2}

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_build_context_prefetches_channel_relations_for_async_stages() -> None:
    """build_context preloads channel reverse relations for async stages."""
    from server.apps.channels.models import (
        AssemblyStyleConfig,
        Channel,
        ChannelBranding,
        ChannelKind,
        NicheConfig,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import build_context

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='prefetch_ctx_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'research', 'depends_on': [], 'queue': 'api'},
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='prefetch_ch',
            kind=ChannelKind.LONGFORM,
        )
        await NicheConfig.objects.acreate(
            channel=ch,
            audience='history buffs',
            angle='factual',
        )
        await ChannelBranding.objects.acreate(
            channel=ch,
            thumbnail_palette={'primary': '#112233'},
        )
        await AssemblyStyleConfig.objects.acreate(
            channel=ch,
            camera_movements=['push_in'],
            transition_styles=['hard_cut'],
            sfx_pool_tags=['whoosh'],
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='prefetch test',
        )
        execution = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='research',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(execution)
        assert ctx.channel.niche_config.audience == 'history buffs'
        assert ctx.channel.branding.thumbnail_palette == {
            'primary': '#112233',
        }
        assert ctx.channel.assembly_style_camera_movements == ['push_in']
        assert ctx.channel.assembly_style_sfx_pool_tags == ['whoosh']

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_build_context_minimal_channel_avoids_sync_orm() -> None:
    """Bare channel without optional relations must not sync-query in async."""
    from django.core.exceptions import ObjectDoesNotExist

    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.context import build_context

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='bare_ctx_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'research', 'depends_on': [], 'queue': 'api'},
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='bare_ch',
            kind=ChannelKind.LONGFORM,
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='bare channel test',
        )
        execution = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='research',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(execution)
        assert ctx.channel.wpm == 158
        try:
            _ = ctx.channel.niche_config
        except ObjectDoesNotExist:
            pass

    _run(_inner())


from server.apps.pipelines.models import (
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
    from server.apps.channels.models import (
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
    from unittest.mock import AsyncMock, patch

    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.models import (
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (
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
def test_advance_parks_run_at_budget_hold_when_cap_exceeded(
    orch_run: PipelineRun,
    orch_channel,
) -> None:
    """advance_pipeline_impl parks the run once spend hits the channel cap.

    Regression: RunStatus.BUDGET_HOLD and channel.default_budget_usd both
    existed, but nothing ever compared spend to the cap — a run could spend
    without limit. dummy_a must not be (re)enqueued once over budget.
    """
    from decimal import Decimal
    from unittest.mock import AsyncMock, patch

    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.models import RunStatus, StageExecution
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    orch_channel.default_budget_usd = Decimal('5.00')
    orch_channel.save(update_fields=['default_budget_usd'])
    orch_run.total_cost_usd = Decimal('5.01')
    orch_run.save(update_fields=['total_cost_usd'])

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ) as mock_enqueue,
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(orch_run.id))

        mock_enqueue.assert_not_called()
        assert not await StageExecution.objects.filter(
            run=orch_run,
        ).aexists()

    _run(_inner())

    orch_run.refresh_from_db()
    assert orch_run.status == RunStatus.BUDGET_HOLD


@pytest.mark.django_db(transaction=True)
def test_advance_short_circuits_when_already_at_budget_hold(
    orch_run: PipelineRun,
    orch_channel,
) -> None:
    """A subsequent advance on an already-held run is a cheap no-op.

    Once parked, advance_pipeline_impl should not repeat the over-budget
    check/log every time an in-flight sibling stage's completion re-kicks
    the DAG evaluation — it just re-confirms the hold.
    """
    from decimal import Decimal
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import RunStatus, StageExecution
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    orch_channel.default_budget_usd = Decimal('5.00')
    orch_channel.save(update_fields=['default_budget_usd'])
    orch_run.total_cost_usd = Decimal('5.01')
    orch_run.status = RunStatus.BUDGET_HOLD
    orch_run.save(update_fields=['total_cost_usd', 'status'])

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ) as mock_enqueue,
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(orch_run.id))

        mock_enqueue.assert_not_called()
        assert not await StageExecution.objects.filter(
            run=orch_run,
        ).aexists()

    _run(_inner())

    orch_run.refresh_from_db()
    assert orch_run.status == RunStatus.BUDGET_HOLD


@pytest.mark.django_db(transaction=True)
def test_advance_does_not_hold_when_under_budget(
    orch_run: PipelineRun,
    orch_channel,
) -> None:
    """A run under the channel's budget cap advances normally."""
    from decimal import Decimal
    from unittest.mock import AsyncMock, patch

    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.models import RunStatus, StageStatus
    from server.apps.pipelines.selectors import get_run_detail
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    orch_channel.default_budget_usd = Decimal('5.00')
    orch_channel.save(update_fields=['default_budget_usd'])
    orch_run.total_cost_usd = Decimal('1.00')
    orch_run.save(update_fields=['total_cost_usd'])

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

    _run(_inner())

    orch_run.refresh_from_db()
    assert orch_run.status != RunStatus.BUDGET_HOLD
    detail = get_run_detail(str(orch_run.id))
    dummy_a = next(s for s in detail.stages if s.stage_key == 'dummy_a')
    assert dummy_a.status == StageStatus.QUEUED


@pytest.mark.django_db(transaction=True)
def test_advance_marks_run_completed_when_all_stages_succeed(
    orch_run: PipelineRun,
) -> None:
    """When all stages SUCCEEDED, run transitions to COMPLETED."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import (
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (
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
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (
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
def test_advance_waits_before_skipping_unarmed_gate() -> None:
    """Unarmed gates must not skip until depends_on are terminal.

    Early skip unblocks downstream stages with empty upstream (the longform
    narrative_qc / publish failure mode when channel.gates is empty).
    """
    from unittest.mock import AsyncMock, patch

    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='gated_wait_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
                    {
                        'key': 'my_gate',
                        'depends_on': ['dummy_a'],
                        'gate': True,
                        'queue': 'api',
                    },
                    {
                        'key': 'dummy_b',
                        'depends_on': ['my_gate'],
                        'queue': 'api',
                    },
                ],
            },
        )
        ch = await Channel.objects.acreate(
            name='gated_wait_ch',
            kind=ChannelKind.LONGFORM,
            gates=[],
        )
        gated_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='Gate wait test',
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

            assert not await StageExecution.objects.filter(
                run=gated_run,
                stage_key='my_gate',
            ).aexists()
            assert not await StageExecution.objects.filter(
                run=gated_run,
                stage_key='dummy_b',
            ).aexists()

            await StageExecution.objects.filter(
                run=gated_run,
                stage_key='dummy_a',
            ).aupdate(status=StageStatus.SUCCEEDED)
            await advance_pipeline_impl(str(gated_run.id))

        gate_exec = await StageExecution.objects.aget(
            run=gated_run,
            stage_key='my_gate',
        )
        assert gate_exec.status == StageStatus.SKIPPED
        downstream = await StageExecution.objects.filter(
            run=gated_run,
            stage_key='dummy_b',
        ).afirst()
        assert downstream is not None
        assert downstream.status == StageStatus.QUEUED

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_parks_run_at_awaiting_review_for_armed_gate():
    """An armed gate sets run.status=AWAITING_REVIEW and creates a parked execution."""
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    assert exec_.status == StageStatus.NEEDS_INPUT


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_skips_unarmed_gate():
    """A gate NOT in channel.gates is auto-skipped."""
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )
    from server.apps.pipelines.models import (
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

    from server.apps.pipelines.services.orchestrator import (
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
        run=run,
        stage_key='final_gate',
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_advance_pipeline_logs_failed_stage_details(
    channel,
) -> None:
    """pipeline_advanced includes failure details when a stage is FAILED."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    bp = PipelineBlueprint.objects.create(
        name='fail_log_v1',
        kind=PipelineKind.CLIPPING,
        graph={
            'stages': [
                {'key': 'clip_ingest', 'depends_on': []},
                {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
            ],
        },
        is_active=True,
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='failure logging test',
        status=RunStatus.RUNNING,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'asset_id': 'asset-1'},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_transcribe',
        status=StageStatus.FAILED,
        attempt=0,
        error={
            'type': 'RuntimeError',
            'message': 'whisperx failed: module not found',
            'retryable': False,
        },
    )

    from server.apps.pipelines.services.orchestrator import (
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
        patch(
            'server.apps.pipelines.services.orchestrator.logger',
        ) as mock_logger,
    ):
        _run(advance_pipeline_impl(str(run.id)))

    mock_logger.info.assert_called()
    log_kwargs = mock_logger.info.call_args.kwargs
    assert log_kwargs['failures'][0]['stage_key'] == 'clip_transcribe'
    assert 'whisperx failed' in log_kwargs['failures'][0]['message']


@pytest.mark.django_db(transaction=True)
def test_clipping_blueprint_always_arms_gates_regardless_of_channel_gates():
    """CLIPPING blueprints auto-arm all gate nodes even when channel.gates is empty."""
    from unittest.mock import AsyncMock, patch

    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    channel = Channel.objects.create(
        name='Clipping No-Gates Channel',
        kind=ChannelKind.CLIPPING,
        gates=[],  # deliberately empty — reproduces the original bug
    )
    bp = PipelineBlueprint.objects.create(
        name='clip_gate_auto_arm_v1',
        kind=PipelineKind.CLIPPING,
        graph={
            'stages': [
                {
                    'key': 'clip_approval_gate',
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
        topic='clipping gate auto-arm test',
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
    assert run.status == RunStatus.AWAITING_REVIEW, (
        'CLIPPING blueprint gate must park the run at AWAITING_REVIEW '
        'even when channel.gates is empty'
    )
    exec_ = StageExecution.objects.get(run=run, stage_key='clip_approval_gate')
    assert exec_.status == StageStatus.NEEDS_INPUT


@pytest.fixture
def publish_blueprint() -> PipelineBlueprint:
    """A 1-stage blueprint whose only node is the real 'publish' stage key."""
    return PipelineBlueprint.objects.create(
        name='publish_hold_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [{'key': 'publish', 'depends_on': [], 'queue': 'api'}],
        },
    )


@pytest.mark.django_db
def test_publish_rate_limited_false_when_cap_is_zero(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """max_publishes_per_day=0 means unlimited — never rate-limited."""
    from server.apps.pipelines.services.orchestrator import (
        _publish_rate_limited,
    )

    orch_channel.max_publishes_per_day = 0
    orch_channel.save(update_fields=['max_publishes_per_day'])

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='unlimited cap',
    )

    assert _publish_rate_limited(run) is False


@pytest.mark.django_db(transaction=True)
def test_advance_parks_run_at_publish_hold_when_daily_cap_reached(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """Publish stage does not enqueue once today's PublishJob count hits the cap."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    orch_channel.max_publishes_per_day = 1
    orch_channel.save(update_fields=['max_publishes_per_day'])

    prior_run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='already published today',
    )
    PublishJob.objects.create(
        run=prior_run,
        channel=orch_channel,
        status=PublishStatus.COMPLETED,
    )

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='second video today',
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
    assert run.status == RunStatus.PUBLISH_HOLD
    assert not run.stages.filter(stage_key='publish').exists()


@pytest.fixture
def multi_stage_publish_blueprint() -> PipelineBlueprint:
    """A 2-stage blueprint (qc -> publish).

    So PUBLISH_HOLD isn't the only entry `states` could ever hold —
    reproduces the overwrite bug that a 1-node blueprint's empty `states`
    dict accidentally hides.
    """
    return PipelineBlueprint.objects.create(
        name='publish_hold_multi_stage_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'qc', 'depends_on': [], 'queue': 'render'},
                {'key': 'publish', 'depends_on': ['qc'], 'queue': 'api'},
            ],
        },
    )


@pytest.mark.django_db(transaction=True)
def test_advance_does_not_overwrite_publish_hold_with_completed(
    multi_stage_publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """A run with every upstream stage SUCCEEDED stays PUBLISH_HOLD.

    Not COMPLETED, when the only remaining node ('publish') is rate-limited.
    """
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import StageExecution, StageStatus
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    orch_channel.max_publishes_per_day = 1
    orch_channel.save(update_fields=['max_publishes_per_day'])

    prior_run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=multi_stage_publish_blueprint,
        blueprint_snapshot=multi_stage_publish_blueprint.graph,
        topic='already published today',
    )
    PublishJob.objects.create(
        run=prior_run,
        channel=orch_channel,
        status=PublishStatus.COMPLETED,
    )

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=multi_stage_publish_blueprint,
        blueprint_snapshot=multi_stage_publish_blueprint.graph,
        topic='second video today, qc already done',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='qc',
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
        _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    assert run.status == RunStatus.PUBLISH_HOLD
    assert not run.stages.filter(stage_key='publish').exists()


@pytest.mark.django_db(transaction=True)
def test_advance_enqueues_publish_when_under_cap(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """Publish stage enqueues normally when today's PublishJob count is under the cap."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import StageStatus
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    orch_channel.max_publishes_per_day = 1
    orch_channel.save(update_fields=['max_publishes_per_day'])

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='first video today',
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

    assert run.stages.filter(
        stage_key='publish',
        status=StageStatus.QUEUED,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_resume_publish_held_runs_advances_each_held_run(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """The daily task resumes runs parked at PUBLISH_HOLD."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.tasks import resume_publish_held_runs

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='held run',
        status=RunStatus.PUBLISH_HOLD,
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
        _run(resume_publish_held_runs())

    run.refresh_from_db()
    assert run.status != RunStatus.PUBLISH_HOLD
