"""Tests for execute_stage_impl executor logic."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine synchronously, closing DB connections on exit."""
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


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    """Blueprint with a single dummy_a stage."""
    return PipelineBlueprint.objects.create(
        name='exec_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
            ],
        },
    )


@pytest.fixture
def channel():
    """A test channel."""
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
    )

    return Channel.objects.create(
        name='Exec Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel) -> PipelineRun:
    """A pipeline run using the exec_test blueprint."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Executor test',
    )


@pytest.mark.django_db(transaction=True)
def test_execute_stage_succeeds_for_dummy_a(run: PipelineRun) -> None:
    """dummy_a stage should run successfully and store output."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )

    async def _inner() -> None:
        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            status=StageStatus.QUEUED,
            input_hash='',
        )
        with patch(
            'server.apps.pipelines.services.executor.kick_advance',
            new=AsyncMock(),
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.SUCCEEDED
        assert refreshed.output == {'result': 'a_done'}
        assert refreshed.started_at is not None
        assert refreshed.finished_at is not None

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_uses_cache_on_matching_input_hash(
    run: PipelineRun,
) -> None:
    """Cache hit: matching input_hash copies output at zero cost."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )

    async def _inner() -> None:
        await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            input_hash='same_hash',
            status=StageStatus.SUCCEEDED,
            output={'result': 'cached_output'},
            attempt=0,
        )
        new_exec = await StageExecution.objects.acreate(
            run=run,
            stage_key='dummy_a',
            input_hash='same_hash',
            status=StageStatus.QUEUED,
            attempt=1,
        )
        with patch(
            'server.apps.pipelines.services.executor.kick_advance',
            new=AsyncMock(),
        ):
            await execute_stage_impl(str(new_exec.id))

        refreshed = await StageExecution.objects.aget(id=new_exec.id)
        assert refreshed.status == StageStatus.SUCCEEDED
        assert refreshed.output == {'result': 'cached_output'}
        assert refreshed.cost_usd == 0

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_fails_after_exhausting_retries(
    run: PipelineRun,
) -> None:
    """After max_retries exceeded, stage is marked FAILED retryable=True."""
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
        class _ExhaustedStage(Stage):
            """Test stage that always raises RetryableProviderError."""

            key = '_exhausted_stage'
            queue = 'api'
            max_retries = 1
            timeout_s = 10

            async def run(self, ctx: StageContext) -> dict:
                """Raise a retryable error unconditionally."""
                raise RetryableProviderError('rate limited', provider='test')

        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='_exhausted_stage',
            status=StageStatus.QUEUED,
            input_hash='',
            max_retries=1,
            attempt=1,  # Already at max_retries, so next fail should stick
        )
        with (
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.FAILED
        assert refreshed.error['retryable'] is True

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_execute_stage_never_retries_fatal_provider_error(
    run: PipelineRun,
) -> None:
    """FatalProviderError goes to NEEDS_INPUT and never schedules a retry.

    Regression test for the diarization-timeout CPU-starvation spiral: a
    FatalProviderError (e.g. a diarization chunk timeout) must never
    trigger `_schedule_retry`, even when `attempt < max_retries` — an
    automatic retry on a resource-exhaustion failure just compounds it.
    """
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
            """Test stage that always raises FatalProviderError."""

            key = '_fatal_stage'
            queue = 'api'
            max_retries = 2
            timeout_s = 10

            async def run(self, ctx: StageContext) -> dict:
                """Raise a fatal error unconditionally."""
                raise FatalProviderError(
                    'diarization chunk 0 exceeded 600s',
                    provider='pyannote',
                    error_code='diarization_chunk_timeout',
                )

        exec_ = await StageExecution.objects.acreate(
            run=run,
            stage_key='_fatal_stage',
            status=StageStatus.QUEUED,
            input_hash='',
            max_retries=2,
            attempt=0,  # Well under max_retries — a retry-prone bug would fire here.
        )
        with (
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                new=AsyncMock(),
            ) as mock_execute_stage_kiq,
        ):
            await execute_stage_impl(str(exec_.id))

        refreshed = await StageExecution.objects.aget(id=exec_.id)
        assert refreshed.status == StageStatus.NEEDS_INPUT
        assert refreshed.error['type'] == 'FatalProviderError'
        mock_execute_stage_kiq.assert_not_called()

    _run(_inner())
