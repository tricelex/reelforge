"""
End-to-end test of the pipeline engine using the 3-stage dummy blueprint.

Stages: dummy_a -> dummy_b -> dummy_c (linear dependency chain).
No real TaskIQ workers -- advance_pipeline_impl and execute_stage_impl are
called directly to simulate the full engine flow.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)

DUMMY_BLUEPRINT_GRAPH = {
    'stages': [
        {'key': 'dummy_a', 'depends_on': [], 'queue': 'api'},
        {'key': 'dummy_b', 'depends_on': ['dummy_a'], 'queue': 'api'},
        {'key': 'dummy_c', 'depends_on': ['dummy_b'], 'queue': 'api'},
    ],
}


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine synchronously, closing DB connections before exit."""
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        """Close all Django DB connections to avoid teardown timeouts."""
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


@pytest.fixture
def channel() -> Channel:
    """Create a test channel."""
    return Channel.objects.create(name='E2E Channel', kind=ChannelKind.LONGFORM)


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    """Create the 3-stage dummy blueprint."""
    return PipelineBlueprint.objects.create(
        name='dummy_v1',
        kind=PipelineKind.LONGFORM,
        graph=DUMMY_BLUEPRINT_GRAPH,
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel: Channel) -> PipelineRun:
    """Create a PipelineRun for the dummy blueprint."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=DUMMY_BLUEPRINT_GRAPH,
        topic='3-stage dummy end-to-end test',
    )


@pytest.mark.django_db(transaction=True)
def test_3_stage_dummy_blueprint_runs_to_completion(
    run: PipelineRun,
) -> None:
    """3-stage linear dummy blueprint advances to COMPLETED via the engine.

    Simulates advance -> execute cycle:
    1. advance_pipeline_impl enqueues dummy_a
    2. execute_stage_impl runs dummy_a -> SUCCEEDED, kicks advance
    3. advance enqueues dummy_b
    4. execute_stage_impl runs dummy_b -> SUCCEEDED, kicks advance
    5. advance enqueues dummy_c
    6. execute_stage_impl runs dummy_c -> SUCCEEDED, kicks advance
    7. advance -> run status = COMPLETED
    """
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    execution_queue: list[str] = []

    async def fake_execute_stage_kiq(exec_id: str) -> None:
        """Capture enqueued execution IDs instead of sending to broker."""
        execution_queue.append(exec_id)

    async def fake_kick_advance(execution: object) -> None:
        """Call advance_pipeline_impl directly instead of enqueueing a task."""
        await advance_pipeline_impl(str(execution.run_id))  # type: ignore[union-attr]

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                side_effect=fake_execute_stage_kiq,
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.executor.kick_advance',
                side_effect=fake_kick_advance,
            ),
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                new=AsyncMock(),
            ),
        ):
            # Step 1: Start -- advance_pipeline_impl enqueues dummy_a
            await advance_pipeline_impl(str(run.id))
            assert len(execution_queue) == 1

            # Steps 2-6: each stage runs; kick_advance enqueues the next
            while execution_queue:
                exec_id = execution_queue.pop(0)
                await execute_stage_impl(exec_id)

        # Verify final run status
        final_run = await PipelineRun.objects.aget(id=run.id)
        assert final_run.status == RunStatus.COMPLETED
        assert final_run.finished_at is not None

        # Verify all three stages succeeded
        stage_map = {
            e.stage_key: e async for e in StageExecution.objects.filter(run=run)
        }
        assert stage_map['dummy_a'].status == StageStatus.SUCCEEDED
        assert stage_map['dummy_b'].status == StageStatus.SUCCEEDED
        assert stage_map['dummy_c'].status == StageStatus.SUCCEEDED

        # dummy_b output carries upstream dummy_a result
        assert stage_map['dummy_b'].output == {
            'result': 'b_done',
            'saw_a': 'a_done',
        }

    _run(_inner())
