"""Coverage tests for pipeline engine edge-cases."""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunCast,
    RunStatus,
    StageExecution,
    StageStatus,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine synchronously, closing DB connections on exit."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    @sync_to_async
    def _close() -> None:
        from django.db import connections  # noqa: PLC0415

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close()

    return asyncio.run(_wrapped())


@pytest.fixture
def channel() -> Channel:
    """Test channel with default publish_mode (review)."""
    return Channel.objects.create(name='Cov Channel', kind=ChannelKind.LONGFORM)


@pytest.fixture
def blueprint(channel: Channel) -> PipelineBlueprint:
    """Blueprint with a single dummy_a stage."""
    return PipelineBlueprint.objects.create(
        name='cov_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
            ],
        },
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel: Channel) -> PipelineRun:
    """Pipeline run using the single-stage coverage blueprint."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Coverage test run',
    )


# ---------------------------------------------------------------------------
# Model __str__ edge-cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stage_execution_str_with_shard_index(run: PipelineRun) -> None:
    """StageExecution.__str__ includes [shard_index] when shard_index is set."""
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='gen_img',
        shard_index=2,
        input_hash='',
    )
    assert str(exec_) == 'gen_img[2] attempt=0 (PENDING)'


@pytest.mark.django_db
def test_run_cast_str(run: PipelineRun, channel: Channel) -> None:
    """RunCast.__str__ returns '<character_name> as <role>'."""
    from server.apps.channels.models import Character  # noqa: PLC0415

    char = Character.objects.create(
        channel=channel,
        name='Alaric',
        appearance_prompt='tall king',
    )
    cast = RunCast.objects.create(run=run, character=char, role='protagonist')
    assert str(cast) == 'Alaric as protagonist'


# ---------------------------------------------------------------------------
# Stage.fan_out default
# ---------------------------------------------------------------------------


def test_fan_out_returns_none() -> None:
    """Stage.fan_out() default returns None (no sharding)."""
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        Stage,
        StageContext,
        register_stage,
    )

    @register_stage
    class _FanStage(Stage):
        """Test stage for fan_out coverage."""

        key = '_fan_out_test_stage'
        queue = 'api'

        async def run(self, ctx: StageContext) -> dict:
            """Return empty dict."""
            return {}

    assert _FanStage().fan_out(MagicMock()) is None
    assert asyncio.run(_FanStage().run(MagicMock())) == {}


# ---------------------------------------------------------------------------
# tasks.py function bodies
# ---------------------------------------------------------------------------


def test_execute_stage_task_body_calls_impl() -> None:
    """execute_stage task body delegates directly to execute_stage_impl."""

    async def _inner() -> None:
        from server.apps.pipelines.tasks import execute_stage  # noqa: PLC0415

        with patch(
            'server.apps.pipelines.services.executor.execute_stage_impl',
            new=AsyncMock(),
        ) as mock_impl:
            await execute_stage('fake-id')
            mock_impl.assert_called_once_with('fake-id')

    asyncio.run(_inner())


def test_advance_pipeline_task_body_calls_impl() -> None:
    """advance_pipeline task body delegates to advance_pipeline_impl."""

    async def _inner() -> None:
        from server.apps.pipelines.tasks import (  # noqa: PLC0415
            advance_pipeline,
        )

        with patch(
            'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
            new=AsyncMock(),
        ) as mock_impl:
            await advance_pipeline('fake-run-id')
            mock_impl.assert_called_once_with('fake-run-id')

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# executor.py: kick_advance and execute_stage_kiq wrappers
# ---------------------------------------------------------------------------


def test_kick_advance_sends_advance_pipeline_kiq() -> None:
    """kick_advance calls advance_pipeline.kiq with the run_id string."""

    async def _inner() -> None:
        from server.apps.pipelines.services.executor import (  # noqa: PLC0415
            kick_advance,
        )

        mock_exec = MagicMock()
        mock_exec.run_id = 'run-abc'
        with patch('server.apps.pipelines.tasks.advance_pipeline') as mock_task:
            mock_task.kiq = AsyncMock()
            await kick_advance(mock_exec)
            mock_task.kiq.assert_called_once_with('run-abc')

    asyncio.run(_inner())


def test_executor_execute_stage_kiq_sends_kiq() -> None:
    """executor.execute_stage_kiq calls execute_stage.kiq."""

    async def _inner() -> None:
        from server.apps.pipelines.services.executor import (  # noqa: PLC0415
            execute_stage_kiq,
        )

        with patch('server.apps.pipelines.tasks.execute_stage') as mock_task:
            mock_task.kiq = AsyncMock()
            await execute_stage_kiq('exec-xyz')
            mock_task.kiq.assert_called_once_with('exec-xyz')

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# orchestrator.py: publish_sse and execute_stage_kiq wrappers
# ---------------------------------------------------------------------------


def test_publish_sse_sends_json_payload() -> None:
    """publish_sse encodes data as JSON bytes and publishes pipeline event."""

    async def _inner() -> None:
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            publish_sse,
        )

        with patch(
            'server.apps.pipelines.services.orchestrator.publish_pipeline_event',
            new=AsyncMock(),
        ) as mock_pub:
            await publish_sse('run-1', {'type': 'test.event'})
            mock_pub.assert_called_once()
            run_id_arg, data_arg = mock_pub.call_args[0]
            assert run_id_arg == 'run-1'
            assert json.loads(data_arg.decode()) == {'type': 'test.event'}

    asyncio.run(_inner())


def test_orchestrator_execute_stage_kiq_sends_kiq() -> None:
    """orchestrator.execute_stage_kiq calls execute_stage.kiq."""

    async def _inner() -> None:
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            execute_stage_kiq,
        )

        with patch('server.apps.pipelines.tasks.execute_stage') as mock_task:
            mock_task.kiq = AsyncMock()
            await execute_stage_kiq('exec-abc')
            mock_task.kiq.assert_called_once_with('exec-abc')

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# orchestrator._eval_condition — all branches
# ---------------------------------------------------------------------------


def test_eval_condition_all_branches() -> None:
    """_eval_condition covers empty, review, auto, and unknown conditions."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        _eval_condition,  # noqa: PLC2701
    )

    mock_run = MagicMock()

    # Empty / missing condition → always True
    assert _eval_condition({}, mock_run) is True
    assert _eval_condition({'conditional': ''}, mock_run) is True

    # review mode
    mock_run.channel.publish_mode = 'review'
    assert (
        _eval_condition(
            {'conditional': "channel.publish_mode == 'review'"},
            mock_run,
        )
        is True
    )
    assert (
        _eval_condition(
            {'conditional': "channel.publish_mode == 'auto'"},
            mock_run,
        )
        is False
    )

    # auto mode
    mock_run.channel.publish_mode = 'auto'
    assert (
        _eval_condition(
            {'conditional': "channel.publish_mode == 'auto'"},
            mock_run,
        )
        is True
    )
    assert (
        _eval_condition(
            {'conditional': "channel.publish_mode == 'review'"},
            mock_run,
        )
        is False
    )

    # Unknown condition string → False
    result = _eval_condition({'conditional': 'unknown.expression'}, mock_run)
    assert result is False


# ---------------------------------------------------------------------------
# prompt_renderer
# ---------------------------------------------------------------------------


def test_prompt_renderer_get_version_id() -> None:
    """get_version_id returns the pinned UUID or None when not in snapshot."""
    from server.apps.pipelines.services.prompt_renderer import (  # noqa: PLC0415
        PromptRenderer,
    )

    renderer = PromptRenderer({'research': 'uuid-123'})

    async def _inner() -> None:
        assert await renderer.get_version_id('research') == 'uuid-123'
        assert await renderer.get_version_id('missing') is None

    asyncio.run(_inner())


def test_prompt_renderer_render_returns_empty_when_no_version() -> None:
    """render() returns ('', '') when no PromptVersion found."""
    from server.apps.pipelines.services.prompt_renderer import (  # noqa: PLC0415
        PromptRenderer,
    )

    renderer = PromptRenderer({})

    async def _inner() -> None:
        with patch('server.apps.prompts.models.PromptVersion') as mock_cls:
            mock_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=None,
            )
            result = await renderer.render('research', {})
            assert result == ('', '')

    asyncio.run(_inner())


def test_prompt_renderer_render_returns_prompts_with_version_id() -> None:
    """render() returns (system_prompt, user_prompt) when a version is found."""
    from server.apps.pipelines.services.prompt_renderer import (  # noqa: PLC0415
        PromptRenderer,
    )

    renderer = PromptRenderer({'research': 'uuid-456'})
    mock_pv = MagicMock()
    mock_pv.system_prompt = 'You are a researcher.'
    mock_pv.user_prompt = 'Research this topic: {topic}'

    async def _inner() -> None:
        with patch('server.apps.prompts.models.PromptVersion') as mock_pv_cls:
            mock_pv_cls.objects.aget = AsyncMock(return_value=mock_pv)
            result = await renderer.render('research', {'topic': 'AI'})
            assert result == (
                'You are a researcher.',
                'Research this topic: {topic}',
            )
            mock_pv_cls.objects.aget.assert_called_once_with(id='uuid-456')

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# asset_writer.save
# ---------------------------------------------------------------------------


def test_asset_writer_save_creates_asset_row() -> None:
    """AssetWriter.save computes checksum, saves file, and returns the Asset."""
    import hashlib  # noqa: PLC0415

    from server.apps.pipelines.services.asset_writer import (  # noqa: PLC0415
        AssetWriter,
    )

    mock_execution = MagicMock()
    mock_execution.run = MagicMock()
    writer = AssetWriter(mock_execution)

    content = b'fake image bytes'
    expected_checksum = hashlib.sha256(content).hexdigest()

    mock_asset = MagicMock()
    mock_asset.file = MagicMock()
    mock_asset.asave = AsyncMock()

    async def _inner() -> None:
        with patch('server.apps.assets.models.Asset') as mock_asset_cls:
            mock_asset_cls.return_value = mock_asset
            result = await writer.save(
                'image',
                content,
                'test.png',
                'image/png',
            )

        assert result is mock_asset
        mock_asset_cls.assert_called_once_with(
            kind='image',
            mime='image/png',
            checksum=expected_checksum,
            run=mock_execution.run,
            stage_execution=mock_execution,
        )
        mock_asset.file.save.assert_called_once()
        mock_asset.asave.assert_called_once()

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# context.py: missing upstream (dep_exec is None branch)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_build_context_missing_upstream_gives_empty_dict() -> None:
    """build_context gives empty upstream when dep has no SUCCEEDED exec."""
    from server.apps.pipelines.services.context import (  # noqa: PLC0415
        build_context,
    )

    async def _inner() -> None:
        ch = await Channel.objects.acreate(
            name='ctx_miss_ch',
            kind=ChannelKind.LONGFORM,
        )
        bp = await PipelineBlueprint.objects.acreate(
            name='ctx_miss_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {'key': 'step_a', 'depends_on': [], 'queue': 'api'},
                    {'key': 'step_b', 'depends_on': ['step_a'], 'queue': 'api'},
                ],
            },
        )
        ctx_run = await PipelineRun.objects.acreate(
            channel=ch,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='missing upstream test',
        )
        # Create step_b execution but no SUCCEEDED step_a
        exec_b = await StageExecution.objects.acreate(
            run=ctx_run,
            stage_key='step_b',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        ctx = await build_context(exec_b)
        assert ctx.upstream == {}

    _run(_inner())


# ---------------------------------------------------------------------------
# executor.py: error paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_execute_stage_unknown_stage_key_marks_failed(run: PipelineRun) -> None:
    """Unknown stage key → execution marked FAILED with descriptive error."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )

    async def _inner() -> None:
        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='nonexistent_stage_xyz',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.kick_advance',
            new=AsyncMock(),
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.FAILED
        assert 'Unknown stage key' in refreshed.error['message']

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_fatal_error_marks_needs_input(run: PipelineRun) -> None:
    """Stage raises FatalProviderError → execution status NEEDS_INPUT."""
    import server.apps.pipelines.stages.dummy  # noqa: F401, PLC0415
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        Stage,
        StageContext,
        register_stage,
    )
    from server.common.exceptions import FatalProviderError  # noqa: PLC0415

    async def _inner() -> None:
        @register_stage
        class _FatalStage(Stage):
            """Stage that always raises FatalProviderError."""

            key = '_fatal_stage_cov'
            queue = 'api'
            max_retries = 2
            timeout_s = 10

            async def run(self, ctx: StageContext) -> dict:
                """Raise a fatal error unconditionally."""
                raise FatalProviderError('invalid api key', provider='openai')

        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='_fatal_stage_cov',
            status=StageStatus.QUEUED,
            input_hash='',
            max_retries=2,
            attempt=0,
        )
        with patch(
            'server.apps.pipelines.services.executor.kick_advance',
            new=AsyncMock(),
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.NEEDS_INPUT
        assert refreshed.error['retryable'] is False
        assert refreshed.error['type'] == 'FatalProviderError'

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_schedules_retry_when_under_max_retries(
    run: PipelineRun,
) -> None:
    """RetryableProviderError → marks FAILED and enqueues next attempt."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        Stage,
        StageContext,
        register_stage,
    )
    from server.common.exceptions import RetryableProviderError  # noqa: PLC0415

    async def _inner() -> None:
        @register_stage
        class _RetryStage(Stage):
            """Stage that always raises RetryableProviderError."""

            key = '_retry_stage_cov'
            queue = 'api'
            max_retries = 2
            timeout_s = 10

            async def run(self, ctx: StageContext) -> dict:
                """Raise a retryable error unconditionally."""
                raise RetryableProviderError('rate limited', provider='test')

        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='_retry_stage_cov',
            status=StageStatus.QUEUED,
            input_hash='',
            max_retries=2,
            attempt=0,
        )
        with (
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                new=AsyncMock(),
            ) as mock_kiq,
        ):
            await execute_stage_impl(str(exec_.id))

        # Attempt 0 should be FAILED
        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.FAILED

        # A new attempt 1 should have been created
        next_attempt = await StageExecution.objects.filter(
            run=run,
            stage_key='_retry_stage_cov',
            attempt=1,
        ).afirst()
        assert next_attempt is not None
        assert next_attempt.status == StageStatus.QUEUED
        mock_kiq.assert_called_once_with(str(next_attempt.id))

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_generic_exception_marks_failed(run: PipelineRun) -> None:
    """Unexpected exception in stage.run → execution marked FAILED."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        Stage,
        StageContext,
        register_stage,
    )

    async def _inner() -> None:
        @register_stage
        class _BrokenStage(Stage):
            """Stage that raises a generic ValueError."""

            key = '_broken_stage_cov'
            queue = 'api'
            max_retries = 1
            timeout_s = 10

            async def run(self, ctx: StageContext) -> dict:
                """Raise an unexpected generic error."""
                raise ValueError('something went very wrong')

        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='_broken_stage_cov',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.kick_advance',
            new=AsyncMock(),
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.FAILED
        assert refreshed.error['type'] == 'ValueError'
        assert 'something went very wrong' in refreshed.error['message']

    _run(_inner())


# ---------------------------------------------------------------------------
# orchestrator.py: advance_pipeline_impl edge-cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_advance_marks_run_failed_when_stage_fails(run: PipelineRun) -> None:
    """When a stage is FAILED, advance sets run status to FAILED."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.FAILED,
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
            await advance_pipeline_impl(str(run.id))

        refreshed = await PipelineRun.objects.aget(id=run.id)
        assert refreshed.status == RunStatus.FAILED
        assert refreshed.finished_at is not None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_noop_for_completed_run(run: PipelineRun) -> None:
    """advance_pipeline_impl is a no-op when run is already COMPLETED."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        run.status = RunStatus.COMPLETED
        await run.asave(update_fields=['status'])

        mock_kiq = AsyncMock()
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=mock_kiq,
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(run.id))

        mock_kiq.assert_not_called()

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_empty_blueprint_empty_states(channel: Channel) -> None:
    """Empty blueprint → no stages → _update_run_status_sync early-returns."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        empty_bp = await PipelineBlueprint.objects.acreate(
            name='empty_v1',
            kind=PipelineKind.LONGFORM,
            graph={'stages': []},
        )
        empty_run = await PipelineRun.objects.acreate(
            channel=channel,
            blueprint=empty_bp,
            blueprint_snapshot=empty_bp.graph,
            topic='Empty blueprint test',
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
            await advance_pipeline_impl(str(empty_run.id))

        refreshed = await PipelineRun.objects.aget(id=empty_run.id)
        assert refreshed.status == RunStatus.PENDING  # unchanged

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_running_run_with_queued_stage_no_status_change(
    run: PipelineRun,
) -> None:
    """RUNNING run + QUEUED stage: status unchanged, no save triggered."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        # Mark run as RUNNING but keep started_at=None to trigger line 133->exit
        run.status = RunStatus.RUNNING
        await run.asave(update_fields=['status'])

        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.QUEUED,
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
            await advance_pipeline_impl(str(run.id))

        refreshed = await PipelineRun.objects.aget(id=run.id)
        assert refreshed.status == RunStatus.RUNNING  # unchanged

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_uses_latest_attempt_for_stage_state(run: PipelineRun) -> None:
    """_get_stage_states uses the highest attempt when multiple exist."""
    import server.apps.pipelines.stages.dummy  # noqa: F401, PLC0415
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        # attempt 0 FAILED, attempt 1 SUCCEEDED — engine must use attempt 1
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            attempt=0,
            status=StageStatus.FAILED,
            input_hash='hash0',
        )
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            attempt=1,
            status=StageStatus.SUCCEEDED,
            input_hash='hash1',
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
            await advance_pipeline_impl(str(run.id))

        refreshed = await PipelineRun.objects.aget(id=run.id)
        assert refreshed.status == RunStatus.COMPLETED

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_pending_run_needs_input_stage_no_save(
    run: PipelineRun,
) -> None:
    """PENDING run + NEEDS_INPUT stage: no status change, no save."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        # NEEDS_INPUT → no QUEUED/RUNNING in values → elif False (112->exit)
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.NEEDS_INPUT,
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
            await advance_pipeline_impl(str(run.id))

        refreshed = await PipelineRun.objects.aget(id=run.id)
        assert refreshed.status == RunStatus.PENDING  # unchanged, no save
        assert refreshed.started_at is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_skips_unknown_stage_key_silently(channel: Channel) -> None:
    """Stage key absent from STAGE_REGISTRY is skipped silently."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        bp = await PipelineBlueprint.objects.acreate(
            name='unknown_stage_v1',
            kind=PipelineKind.LONGFORM,
            graph={
                'stages': [
                    {
                        'key': 'nonexistent_stage_xyz',
                        'depends_on': [],
                        'queue': 'api',
                    },
                ],
            },
        )
        the_run = await PipelineRun.objects.acreate(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot=bp.graph,
            topic='Unknown stage test',
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
            await advance_pipeline_impl(str(the_run.id))

        count = await StageExecution.objects.filter(run=the_run).acount()
        assert count == 0

    _run(_inner())
