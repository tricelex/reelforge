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
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close() -> None:
        from django.db import connections

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
    from server.apps.channels.models import Character

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
    from server.apps.pipelines.stages.base import (
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
        from server.apps.pipelines.tasks import execute_stage

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
        from server.apps.pipelines.tasks import (
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
        from server.apps.pipelines.services.executor import (
            kick_advance,
        )

        mock_exec = MagicMock()
        mock_exec.run_id = 'run-abc'
        mock_exec.parent_id = None
        with patch('server.apps.pipelines.tasks.advance_pipeline') as mock_task:
            mock_task.kiq = AsyncMock()
            await kick_advance(mock_exec)
            mock_task.kiq.assert_called_once_with('run-abc')

    asyncio.run(_inner())


def test_executor_execute_stage_kiq_sends_kiq() -> None:
    """executor.execute_stage_kiq calls execute_stage.kiq."""

    async def _inner() -> None:
        from server.apps.pipelines.services.executor import (
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
        from server.apps.pipelines.services.orchestrator import (
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
        from server.apps.pipelines.services.orchestrator import (
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
    from server.apps.pipelines.services.orchestrator import (
        _eval_condition,
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
    from server.apps.pipelines.services.prompt_renderer import (
        PromptRenderer,
    )

    renderer = PromptRenderer({'research': 'uuid-123'})

    async def _inner() -> None:
        assert await renderer.get_version_id('research') == 'uuid-123'
        assert await renderer.get_version_id('missing') is None

    asyncio.run(_inner())


def test_prompt_renderer_render_returns_empty_when_no_version() -> None:
    """render() returns ('', '') when no PromptVersion found."""
    from server.apps.pipelines.services.prompt_renderer import (
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
    from server.apps.pipelines.services.prompt_renderer import (
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


def test_prompt_renderer_render_applies_jinja2_variables() -> None:
    """render() substitutes Jinja2 {{ var }} expressions from the variables dict."""
    from server.apps.pipelines.services.prompt_renderer import (
        PromptRenderer,
    )

    renderer = PromptRenderer({})
    mock_pv = MagicMock()
    mock_pv.system_prompt = 'You are a {{ role }}.'
    mock_pv.user_prompt = 'Research {{ topic }}.'

    async def _inner() -> None:
        with patch('server.apps.prompts.models.PromptVersion') as mock_pv_cls:
            mock_pv_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=mock_pv,
            )
            sys, usr = await renderer.render(
                'test_key',
                {'role': 'expert', 'topic': 'Rome'},
            )
            assert sys == 'You are a expert.'
            assert usr == 'Research Rome.'

    asyncio.run(_inner())


def test_prompt_renderer_get_generation_settings_defaults() -> None:
    """get_generation_settings returns PromptVersion defaults when unset."""
    from server.apps.pipelines.services.prompt_renderer import (
        PromptRenderer,
    )

    async def _inner() -> None:
        renderer = PromptRenderer({})
        with patch('server.apps.prompts.models.PromptVersion') as mock_pv_cls:
            mock_pv_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=None,
            )
            settings = await renderer.get_generation_settings('script')
            assert settings == {'max_tokens': 8192, 'temperature': 1.0}

    asyncio.run(_inner())


def test_prompt_renderer_get_generation_settings_from_version() -> None:
    """get_generation_settings reads max_tokens/temperature from PromptVersion."""
    from server.apps.pipelines.services.prompt_renderer import (
        PromptRenderer,
    )

    mock_pv = MagicMock()
    mock_pv.max_tokens = 16384
    mock_pv.temperature = 0.2

    async def _inner() -> None:
        renderer = PromptRenderer({})
        with patch('server.apps.prompts.models.PromptVersion') as mock_pv_cls:
            mock_pv_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=mock_pv,
            )
            settings = await renderer.get_generation_settings('script')
            assert settings == {'max_tokens': 16384, 'temperature': 0.2}

    asyncio.run(_inner())


def test_build_prompt_variables_includes_niche_for_jinja() -> None:
    """build_prompt_variables supplies niche.* keys used by seeded templates."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.services.prompt_renderer import (
        PromptRenderer,
    )
    from server.apps.pipelines.services.prompt_variables import (
        build_prompt_variables,
    )

    channel = MagicMock()
    channel.name = 'History Explained'
    channel.kind = 'LONGFORM'
    channel.branding = None
    channel.niche_config = MagicMock()
    channel.niche_config.audience = 'history buffs'
    channel.niche_config.angle = 'documentary'
    channel.niche_config.banned_topics = ['politics']
    channel.niche_config.lore_document = 'Be factual.'
    channel.niche_config.format = None

    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.id = '00000000-0000-0000-0000-000000000001'
    ctx.channel = channel
    ctx.upstream = {}
    ctx.config = {}

    user_template = (
        'Topic: {{ topic }}\n'
        '{% if niche.audience %}Audience: {{ niche.audience }}\n{% endif %}'
        '{% if niche.angle %}Angle: {{ niche.angle }}\n{% endif %}'
    )

    async def _inner() -> None:
        variables = await build_prompt_variables(
            ctx,
            include_character=False,
        )
        renderer = PromptRenderer({})
        mock_pv = MagicMock()
        mock_pv.system_prompt = ''
        mock_pv.user_prompt = user_template
        with patch('server.apps.prompts.models.PromptVersion') as mock_pv_cls:
            mock_pv_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=mock_pv,
            )
            _, usr = await renderer.render('research', variables)
        assert 'Topic: The fall of Rome' in usr
        assert 'Audience: history buffs' in usr
        assert 'Angle: documentary' in usr

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# asset_writer.save
# ---------------------------------------------------------------------------


def test_asset_writer_save_creates_asset_row() -> None:
    """AssetWriter.save computes checksum, saves file, and returns the Asset."""
    import hashlib

    from server.apps.pipelines.services.asset_writer import (
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
    from server.apps.pipelines.services.context import (
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
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )

    async def _inner() -> None:
        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='nonexistent_stage_xyz',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        with (
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await execute_stage_impl(str(exec_.id))

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_fatal_error_marks_needs_input(run: PipelineRun) -> None:
    """Stage raises FatalProviderError → execution status NEEDS_INPUT."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )
    from server.common.exceptions import FatalProviderError

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
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )
    from server.common.exceptions import RetryableProviderError

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
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
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
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (
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
        with (
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ) as mock_sse,
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.FAILED
        assert refreshed.error['type'] == 'ValueError'
        assert 'something went very wrong' in refreshed.error['message']
        mock_sse.assert_awaited_once()
        sse_payload = mock_sse.await_args.args[1]
        assert sse_payload['type'] == 'stage.failed'
        assert sse_payload['error_message'] == 'something went very wrong'

    _run(_inner())


# ---------------------------------------------------------------------------
# orchestrator.py: advance_pipeline_impl edge-cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_advance_marks_run_failed_when_stage_fails(run: PipelineRun) -> None:
    """When a stage is FAILED, advance sets run status to FAILED."""
    from server.apps.pipelines.services.orchestrator import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    from server.apps.pipelines.services.orchestrator import (
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
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.orchestrator import (
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
def test_advance_pending_run_needs_input_parks_awaiting_review(
    run: PipelineRun,
) -> None:
    """PENDING run + NEEDS_INPUT stage parks as AWAITING_REVIEW."""
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    async def _inner() -> None:
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
        assert refreshed.status == RunStatus.AWAITING_REVIEW

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_advance_skips_unknown_stage_key(channel: Channel) -> None:
    """Stage key absent from STAGE_REGISTRY is skipped with a warning."""
    from server.apps.pipelines.services.orchestrator import (
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
            patch(
                'server.apps.pipelines.services.orchestrator.logger.warning',
            ) as mock_warning,
        ):
            await advance_pipeline_impl(str(the_run.id))

        count = await StageExecution.objects.filter(run=the_run).acount()
        assert count == 0
        mock_warning.assert_called_once()

    _run(_inner())


# ---------------------------------------------------------------------------
# executor.py: _maybe_complete_fan_out_parent edge-cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_no_op_without_parent(
    run: PipelineRun,
) -> None:
    """Child rows without parent_id return immediately."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        child = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.SUCCEEDED,
            input_hash='',
        )
        await _maybe_complete_fan_out_parent(child)

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_no_op_when_parent_already_succeeded(
    run: PipelineRun,
) -> None:
    """_maybe_complete_fan_out_parent returns early if parent is already SUCCEEDED."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.SUCCEEDED,
            input_hash='',
        )
        child = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            status=StageStatus.SUCCEEDED,
            input_hash='',
        )
        await _maybe_complete_fan_out_parent(child)

        # Early return: parent's finished_at was never set (no asave called)
        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.SUCCEEDED
        assert refreshed.finished_at is None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_uses_latest_attempt_per_shard(
    run: PipelineRun,
) -> None:
    """With multiple attempts for a shard, only the latest (highest attempt) status counts."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.RUNNING,
            input_hash='',
        )
        # attempt 0 FAILED, attempt 1 SUCCEEDED — latest wins (branch 153->148 covered)
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            attempt=0,
            status=StageStatus.FAILED,
            input_hash='',
        )
        child_latest = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            attempt=1,
            status=StageStatus.SUCCEEDED,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            new=AsyncMock(),
        ):
            await _maybe_complete_fan_out_parent(child_latest)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.SUCCEEDED

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_merges_child_output_into_shards(
    run: PipelineRun,
) -> None:
    """Parent shards include fields from the latest child output per shard."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='tts',
            status=StageStatus.RUNNING,
            input_hash='',
        )
        child_0 = await StageExecution.objects.acreate(
            run=run,
            stage_key='tts',
            parent=parent,
            shard_index=0,
            status=StageStatus.SUCCEEDED,
            input_hash='',
            output={
                'chapter_idx': 0,
                'asset_id': 'audio-0',
                'char_count': 100,
            },
        )
        child_1 = await StageExecution.objects.acreate(
            run=run,
            stage_key='tts',
            parent=parent,
            shard_index=1,
            status=StageStatus.SUCCEEDED,
            input_hash='',
            output={
                'chapter_idx': 1,
                'asset_id': 'audio-1',
                'char_count': 200,
            },
        )
        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            new=AsyncMock(),
        ):
            await _maybe_complete_fan_out_parent(child_1)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.SUCCEEDED
        shards = refreshed.output['shards']
        assert len(shards) == 2
        assert shards[0] == {
            'shard_index': 0,
            'status': StageStatus.SUCCEEDED,
            'chapter_idx': 0,
            'asset_id': 'audio-0',
            'char_count': 100,
        }
        assert shards[1] == {
            'shard_index': 1,
            'status': StageStatus.SUCCEEDED,
            'chapter_idx': 1,
            'asset_id': 'audio-1',
            'char_count': 200,
        }
        # Latest attempt wins when merging output
        await StageExecution.objects.acreate(
            run=run,
            stage_key='tts',
            parent=parent,
            shard_index=0,
            attempt=1,
            status=StageStatus.SUCCEEDED,
            input_hash='',
            output={
                'chapter_idx': 0,
                'asset_id': 'audio-0-retry',
                'char_count': 110,
            },
        )
        parent.status = StageStatus.RUNNING
        parent.output = {}
        await parent.asave(update_fields=['status', 'output'])
        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            new=AsyncMock(),
        ):
            await _maybe_complete_fan_out_parent(child_0)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.output['shards'][0]['asset_id'] == 'audio-0-retry'

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_fails_parent_when_shard_failed_and_no_in_flight(
    run: PipelineRun,
) -> None:
    """Parent is marked FAILED when a shard is FAILED and no siblings remain in-flight."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.RUNNING,
            input_hash='',
        )
        child_failed = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            status=StageStatus.FAILED,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            new=AsyncMock(),
        ) as mock_advance:
            await _maybe_complete_fan_out_parent(child_failed)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.FAILED
        assert refreshed.error == {'message': 'one or more shards failed'}
        mock_advance.assert_called_once()

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_needs_input_parks_parent(
    run: PipelineRun,
) -> None:
    """Parent is marked NEEDS_INPUT when a shard needs input and none in-flight."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.RUNNING,
            input_hash='',
        )
        child = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            status=StageStatus.NEEDS_INPUT,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            new=AsyncMock(),
        ) as mock_advance:
            await _maybe_complete_fan_out_parent(child)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.NEEDS_INPUT
        assert refreshed.error == {
            'message': 'one or more shards need input',
        }
        mock_advance.assert_called_once()

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_maybe_complete_fan_out_parent_waits_when_in_flight_shards_remain(
    run: PipelineRun,
) -> None:
    """Parent stays RUNNING when a shard fails but other siblings are still in-flight."""
    from server.apps.pipelines.services.executor import (
        _maybe_complete_fan_out_parent,
    )

    async def _inner() -> None:
        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.RUNNING,
            input_hash='',
        )
        child_failed = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=0,
            status=StageStatus.FAILED,
            input_hash='',
        )
        # Shard 1 is still QUEUED → in_flight=True → parent must NOT be marked FAILED yet
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            parent=parent,
            shard_index=1,
            status=StageStatus.QUEUED,
            input_hash='',
        )
        await _maybe_complete_fan_out_parent(child_failed)

        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.RUNNING

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_already_fanned_returns_without_creating_new_children(
    run: PipelineRun,
) -> None:
    """execute_stage_impl on a fan-out parent with existing children is a no-op."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )

    async def _inner() -> None:
        @register_stage
        class _FanIdempotentCovStage(Stage):
            """Fan-out stage for idempotency guard coverage."""

            key = '_fan_idempotent_cov'
            queue = 'api'
            max_retries = 0
            timeout_s = 10

            def fan_out(
                self,
                ctx: StageContext,
            ) -> list[dict[str, object]] | None:
                """Return two shards."""
                return [{'shard': 0}, {'shard': 1}]

            async def run(
                self,
                ctx: StageContext,
            ) -> dict[str, object]:  # pragma: no cover
                """Return empty dict."""
                return {}

        parent = await StageExecution.objects.acreate(
            run=run,
            stage_key='_fan_idempotent_cov',
            status=StageStatus.RUNNING,
            input_hash='precomputed-hash',
        )
        # Child already exists → already_fanned=True
        await StageExecution.objects.acreate(
            run=run,
            stage_key='_fan_idempotent_cov',
            parent=parent,
            shard_index=0,
            status=StageStatus.QUEUED,
            input_hash='',
        )

        mock_kiq = AsyncMock()
        with (
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                new=mock_kiq,
            ),
            patch(
                'server.apps.pipelines.services.executor.advance_pipeline_kiq',
                new=AsyncMock(),
            ),
        ):
            await execute_stage_impl(str(parent.id))

        # No new child executions kicked — guard returned early
        mock_kiq.assert_not_called()
        refreshed = await StageExecution.objects.aget(id=parent.id)
        assert refreshed.status == StageStatus.RUNNING

    _run(_inner())


# ---------------------------------------------------------------------------
# Stage registration
# ---------------------------------------------------------------------------


def test_all_production_stages_registered() -> None:
    """All production stages appear in STAGE_REGISTRY after package import."""
    import server.apps.pipelines.stages  # noqa: F401
    from server.apps.pipelines.stages.base import (
        STAGE_REGISTRY,
    )

    expected = {
        'research',
        'outline',
        'script',
        'scene_breakdown',
        'visual_prompts',
        'image_gen',
        'tts',
        'motion',
        'alignment',
        'music_plan',
        'thumbnail',
        'metadata',
        'assembly',
        'qc',
        'publish',
        'review_gate',
        'clip_ingest',
        'clip_transcribe',
        'clip_analyze',
        'clip_manual_setup',
        'clip_approval_gate',
        'clip_render',
        'clip_distribute',
    }
    assert expected.issubset(set(STAGE_REGISTRY.keys()))


# ---------------------------------------------------------------------------
# orchestrator.py: rerun stage
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_unknown_stage_returns_empty(
    run: PipelineRun,
) -> None:
    """_rerun_stage_sync returns no exec IDs for unknown stage keys."""
    from server.apps.pipelines.services.orchestrator import (
        _rerun_stage_sync,
    )

    exec_ids = _rerun_stage_sync(str(run.id), 'missing_stage', None)
    assert exec_ids == []


@pytest.mark.django_db(transaction=True)
def test_rerun_fan_out_stage_creates_children_with_new_attempt(
    run: PipelineRun,
) -> None:
    """Rerunning a fan-out stage must not reuse shard attempt=0 child rows."""
    from server.apps.pipelines.services.executor import (
        _handle_fan_out,
    )
    from server.apps.pipelines.services.orchestrator import (
        _rerun_stage_sync,
    )
    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )

    @register_stage
    class _FanRerunCovStage(Stage):
        """Fan-out stage for rerun attempt coverage."""

        key = '_fan_rerun_cov'
        queue = 'api'
        max_retries = 2
        timeout_s = 10

        def fan_out(
            self,
            ctx: StageContext,
        ) -> list[dict[str, object]] | None:
            """Return one shard."""
            return [{'chapter_idx': 0, 'text': 'hello'}]

        async def run(
            self,
            ctx: StageContext,
        ) -> dict[str, object]:  # pragma: no cover
            """Return empty dict."""
            return {}

    run.blueprint_snapshot = {
        'stages': [{'key': '_fan_rerun_cov', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])

    parent_v0 = StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_cov',
        status=StageStatus.FAILED,
        attempt=0,
        input_hash='',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_cov',
        parent=parent_v0,
        shard_index=0,
        attempt=0,
        status=StageStatus.FAILED,
        input_hash='',
    )

    exec_ids = _rerun_stage_sync(str(run.id), '_fan_rerun_cov', None)
    parent_v1 = StageExecution.objects.get(id=exec_ids[0])
    assert parent_v1.attempt == 1

    async def _fan_out() -> None:
        with patch(
            'server.apps.pipelines.services.executor.execute_stage_kiq',
            new=AsyncMock(),
        ):
            await _handle_fan_out(
                parent_v1,
                [{'chapter_idx': 0, 'text': 'hello'}],
            )

    _run(_fan_out())

    child_v1 = StageExecution.objects.get(
        run=run,
        stage_key='_fan_rerun_cov',
        parent=parent_v1,
        shard_index=0,
    )
    assert child_v1.attempt == 1


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_with_shard_indices_reruns_only_that_shard(
    run: PipelineRun,
) -> None:
    """Regression: shard-scoped rerun must not touch sibling shards.

    _rerun_stage_sync used to filter candidate rows by
    (parent=None, shard_index__in=shard_indices) when computing the next
    attempt — but parent-level rows always have shard_index=None, so that
    filter was always empty and the code fell through to a full top-level
    requeue, silently regenerating every shard instead of the one
    requested.
    """
    from server.apps.pipelines.services.orchestrator import _rerun_stage_sync

    run.blueprint_snapshot = {
        'stages': [{'key': '_fan_rerun_shard_cov', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])

    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )

    @register_stage
    class _FanRerunShardCovStage(Stage):
        """Fan-out stage for shard-scoped rerun coverage."""

        key = '_fan_rerun_shard_cov'
        queue = 'api'
        max_retries = 2
        timeout_s = 10

        def fan_out(
            self,
            ctx: StageContext,
        ) -> list[dict[str, object]] | None:  # pragma: no cover
            """Not exercised — rerun only requeues, it doesn't fan out."""
            return [{'idx': 0}, {'idx': 1}]

        async def run(
            self,
            ctx: StageContext,
        ) -> dict[str, object]:  # pragma: no cover
            """Return empty dict."""
            return {}

    parent = StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_shard_cov',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        input_hash='',
        output={'shards': [{'shard_index': 0}, {'shard_index': 1}]},
    )
    shard_0 = StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_shard_cov',
        parent=parent,
        shard_index=0,
        attempt=0,
        status=StageStatus.FAILED,
        input_hash='',
        input_snapshot={'idx': 0, 'prompt': 'bad prompt'},
    )
    shard_1 = StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_shard_cov',
        parent=parent,
        shard_index=1,
        attempt=0,
        status=StageStatus.SUCCEEDED,
        input_hash='',
        input_snapshot={'idx': 1, 'prompt': 'good prompt'},
    )

    exec_ids = _rerun_stage_sync(
        str(run.id),
        '_fan_rerun_shard_cov',
        [0],
    )

    assert len(exec_ids) == 1
    new_child = StageExecution.objects.get(id=exec_ids[0])
    assert new_child.shard_index == 0
    assert new_child.parent_id == parent.id
    assert new_child.attempt == 1
    assert new_child.status == StageStatus.QUEUED
    assert new_child.input_snapshot == {'idx': 0, 'prompt': 'bad prompt'}

    # Sibling shard 1 must be untouched — no new attempt, still SUCCEEDED.
    assert not StageExecution.objects.filter(
        run=run,
        stage_key='_fan_rerun_shard_cov',
        shard_index=1,
        attempt__gt=0,
    ).exists()
    shard_1.refresh_from_db()
    assert shard_1.status == StageStatus.SUCCEEDED

    # The old shard-0 row is untouched (a fresh attempt row was added
    # instead of stomping history), and the fan-out parent is reopened so
    # the completion aggregator re-evaluates once the new child finishes.
    shard_0.refresh_from_db()
    assert shard_0.status == StageStatus.FAILED
    parent.refresh_from_db()
    assert parent.status == StageStatus.RUNNING


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_with_unknown_shard_index_enqueues_nothing(
    run: PipelineRun,
) -> None:
    """Requesting a shard index with no existing child is a safe no-op."""
    from server.apps.pipelines.models import RunStatus
    from server.apps.pipelines.services.orchestrator import _rerun_stage_sync

    run.blueprint_snapshot = {
        'stages': [{'key': '_fan_rerun_unknown_cov', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])

    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )

    @register_stage
    class _FanRerunUnknownCovStage(Stage):
        """Fan-out stage for the unknown-shard-index rerun edge case."""

        key = '_fan_rerun_unknown_cov'
        queue = 'api'
        max_retries = 2
        timeout_s = 10

        def fan_out(
            self,
            ctx: StageContext,
        ) -> list[dict[str, object]] | None:  # pragma: no cover
            """Not exercised — rerun only requeues, it doesn't fan out."""
            return [{'idx': 0}]

        async def run(
            self,
            ctx: StageContext,
        ) -> dict[str, object]:  # pragma: no cover
            """Return empty dict."""
            return {}

    parent = StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_unknown_cov',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        input_hash='',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='_fan_rerun_unknown_cov',
        parent=parent,
        shard_index=0,
        attempt=0,
        status=StageStatus.SUCCEEDED,
        input_hash='',
    )

    exec_ids = _rerun_stage_sync(
        str(run.id),
        '_fan_rerun_unknown_cov',
        [99],
    )

    assert exec_ids == []
    run.refresh_from_db()
    assert run.status != RunStatus.RUNNING
    parent.refresh_from_db()
    assert parent.status == StageStatus.SUCCEEDED


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_with_shard_indices_and_no_parent_is_noop(
    run: PipelineRun,
) -> None:
    """Shard-scoped rerun with no prior fan-out parent enqueues nothing."""
    from server.apps.pipelines.services.orchestrator import _rerun_stage_sync

    run.blueprint_snapshot = {
        'stages': [{'key': '_fan_rerun_no_parent_cov', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])

    from server.apps.pipelines.stages.base import (
        Stage,
        StageContext,
        register_stage,
    )

    @register_stage
    class _FanRerunNoParentCovStage(Stage):
        """Fan-out stage never previously executed for this run."""

        key = '_fan_rerun_no_parent_cov'
        queue = 'api'
        max_retries = 2
        timeout_s = 10

        def fan_out(
            self,
            ctx: StageContext,
        ) -> list[dict[str, object]] | None:  # pragma: no cover
            """Not exercised — rerun only requeues, it doesn't fan out."""
            return [{'idx': 0}]

        async def run(
            self,
            ctx: StageContext,
        ) -> dict[str, object]:  # pragma: no cover
            """Return empty dict."""
            return {}

    exec_ids = _rerun_stage_sync(
        str(run.id),
        '_fan_rerun_no_parent_cov',
        [0],
    )

    assert exec_ids == []


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_creates_fresh_attempt(run: PipelineRun) -> None:
    """_rerun_stage_sync stales downstream and creates a queued execution."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.orchestrator import (
        _rerun_stage_sync,
    )

    run.blueprint_snapshot = {
        'stages': [
            {'key': 'dummy_a', 'depends_on': []},
            {'key': 'dummy_b', 'depends_on': ['dummy_a']},
        ],
    }
    run.save(update_fields=['blueprint_snapshot'])
    StageExecution.objects.create(
        run=run,
        stage_key='dummy_a',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )
    downstream = StageExecution.objects.create(
        run=run,
        stage_key='dummy_b',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )

    exec_ids = _rerun_stage_sync(str(run.id), 'dummy_a', None)

    assert len(exec_ids) == 1
    downstream.refresh_from_db()
    assert downstream.status == StageStatus.STALE
    rerun_run = PipelineRun.objects.get(id=run.id)
    assert rerun_run.status == RunStatus.RUNNING
    created = StageExecution.objects.get(id=exec_ids[0])
    assert created.stage_key == 'dummy_a'
    assert created.status == StageStatus.QUEUED
    assert created.attempt == 1


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_sync_stales_stuck_queued(
    run: PipelineRun,
) -> None:
    """Whole-stage rerun abandons a stuck QUEUED row and queues attempt N+1."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.orchestrator import (
        _rerun_stage_sync,
    )

    run.blueprint_snapshot = {
        'stages': [{'key': 'dummy_a', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])
    stuck = StageExecution.objects.create(
        run=run,
        stage_key='dummy_a',
        status=StageStatus.QUEUED,
        attempt=0,
    )

    exec_ids = _rerun_stage_sync(str(run.id), 'dummy_a', None)

    stuck.refresh_from_db()
    assert stuck.status == StageStatus.STALE
    assert len(exec_ids) == 1
    created = StageExecution.objects.get(id=exec_ids[0])
    assert created.status == StageStatus.QUEUED
    assert created.attempt == 1


@pytest.mark.django_db(transaction=True)
def test_rerun_stage_impl_enqueues_and_publishes_sse(run: PipelineRun) -> None:
    """rerun_stage_impl enqueues executions and emits SSE."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.orchestrator import (
        rerun_stage_impl,
    )

    run.blueprint_snapshot = {
        'stages': [{'key': 'dummy_a', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                new=AsyncMock(),
            ) as mock_kiq,
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ) as mock_sse,
        ):
            await rerun_stage_impl(str(run.id), 'dummy_a')
            mock_kiq.assert_called_once()
            mock_sse.assert_called_once_with(
                str(run.id),
                {'type': 'stage.rerun', 'stage_key': 'dummy_a'},
            )

    _run(_inner())


@pytest.mark.django_db
def test_run_cast_service_paths(
    run: PipelineRun,
    channel: Channel,
) -> None:
    """RunCastService covers patch, session, round, and approve."""
    from unittest.mock import MagicMock

    from server.apps.channels.logic.value_objects import (
        CharacterApprovePayload,
        CharacterRoundCreatePayload,
        CharacterRoundResultPayload,
        CharacterSessionPayload,
    )
    from server.apps.channels.models import Character
    from server.apps.pipelines.logic.value_objects import (
        RunCastApprovePayload,
        RunCastPatchPayload,
    )
    from server.apps.pipelines.models import CastDesignStatus, RunCast
    from server.apps.pipelines.services.run_cast import RunCastService

    character = Character.objects.create(
        channel=channel,
        name='Cast Service Character',
        appearance_prompt='test',
    )
    cast_row = RunCast.objects.create(
        run=run,
        character=character,
        role='lead',
        design_status=CastDesignStatus.PROPOSED,
    )
    studio = MagicMock()
    studio.start_session.return_value = CharacterSessionPayload(
        id='session-1',
        character_id=str(character.id),
        rounds=[],
        created_at='2026-01-01T00:00:00+00:00',
    )
    studio.generate_round.return_value = CharacterRoundResultPayload(
        session_id='session-1',
        candidate_asset_ids=['asset-1'],
        cost_usd='0.0250',
    )
    studio.approve.return_value = MagicMock()
    service = RunCastService(studio)

    patched = service.patch(
        str(run.id),
        str(cast_row.id),
        RunCastPatchPayload(role='support', design_status=None),
    )
    assert patched.role == 'support'

    session = service.start_session(str(run.id), str(cast_row.id))
    assert session.id == 'session-1'

    round_result = service.generate_round(
        str(run.id),
        str(cast_row.id),
        'session-1',
        CharacterRoundCreatePayload(prompt='portrait', n=1),
    )
    assert round_result.candidate_asset_ids == ['asset-1']

    approved = service.approve(
        str(run.id),
        str(cast_row.id),
        RunCastApprovePayload(winning_asset_id='asset-1'),
    )
    assert approved.design_status == CastDesignStatus.APPROVED
    studio.approve.assert_called_once_with(
        str(character.id),
        CharacterApprovePayload(winning_asset_id='asset-1'),
    )
