"""Tests for fan-out/sharding support added to execute_stage_impl."""

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
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run coroutine synchronously; close DB connections on exit."""
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


_FAN_GRAPH: dict[str, Any] = {
    'stages': [
        {'key': 'fan_test_parent', 'depends_on': [], 'queue': 'api'},
    ],
}


class FanTestParentStage(Stage):
    """Test fan-out stage returning 3 shards."""

    key = 'fan_test_parent'
    max_retries = 0
    timeout_s = 10

    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Return 3 shard dicts."""
        return [{'shard': 0}, {'shard': 1}, {'shard': 2}]

    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Return shard index from execution."""
        return {'shard_result': ctx.execution.shard_index}


@pytest.fixture(autouse=True)
def _register_fan_stage() -> None:
    """Ensure FanTestParentStage is in STAGE_REGISTRY for each test."""
    register_stage(FanTestParentStage)


@pytest.fixture
def channel() -> Channel:
    """Test channel."""
    return Channel.objects.create(name='Fan Channel', kind=ChannelKind.LONGFORM)


@pytest.fixture
def blueprint() -> PipelineBlueprint:
    """Blueprint with a single fan-out stage."""
    return PipelineBlueprint.objects.create(
        name='fan_v1',
        kind=PipelineKind.LONGFORM,
        graph=_FAN_GRAPH,
    )


@pytest.fixture
def run(blueprint: PipelineBlueprint, channel: Channel) -> PipelineRun:
    """Pipeline run for fan-out tests."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=_FAN_GRAPH,
        topic='fan-out test',
    )


@pytest.mark.django_db(transaction=True)
def test_fan_out_creates_parent_and_three_children(run: PipelineRun) -> None:
    """execute_stage_impl on a fan_out stage creates parent(RUNNING) + 3 children(QUEUED)."""
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        kicked: list[str] = []

        async def fake_execute_stage_kiq(eid: str) -> None:
            kicked.append(eid)

        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                side_effect=fake_execute_stage_kiq,
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(run.id))

        assert len(kicked) == 1
        parent_exec_id = kicked[0]

        from server.apps.pipelines.services.executor import (
            execute_stage_impl,
        )

        child_ids: list[str] = []

        async def fake_child_kiq(eid: str) -> None:
            child_ids.append(eid)

        with (
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                side_effect=fake_child_kiq,
            ),
            patch(
                'server.apps.pipelines.services.executor.advance_pipeline_kiq',
                new=AsyncMock(),
            ),
        ):
            await execute_stage_impl(parent_exec_id)

        parent = await StageExecution.objects.aget(id=parent_exec_id)
        assert parent.status == StageStatus.RUNNING
        assert parent.parent_id is None

        children = [
            e
            async for e in StageExecution.objects.filter(
                parent_id=parent_exec_id,
            ).order_by('shard_index')
        ]
        assert len(children) == 3
        assert [c.shard_index for c in children] == [0, 1, 2]
        assert all(c.status == StageStatus.QUEUED for c in children)
        assert len(child_ids) == 3

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_all_children_succeed_completes_parent(run: PipelineRun) -> None:
    """When all 3 child shards succeed, parent transitions to SUCCEEDED."""
    from server.apps.pipelines.services.executor import (
        execute_stage_impl,
    )
    from server.apps.pipelines.services.orchestrator import (
        advance_pipeline_impl,
    )

    async def _inner() -> None:
        kicked: list[str] = []

        async def fake_orchestrator_kiq(eid: str) -> None:
            kicked.append(eid)

        with (
            patch(
                'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
                side_effect=fake_orchestrator_kiq,
            ),
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ),
        ):
            await advance_pipeline_impl(str(run.id))

        parent_exec_id = kicked[0]
        child_ids: list[str] = []

        async def fake_child_kiq(eid: str) -> None:
            child_ids.append(eid)

        with (
            patch(
                'server.apps.pipelines.services.executor.execute_stage_kiq',
                side_effect=fake_child_kiq,
            ),
            patch(
                'server.apps.pipelines.services.executor.advance_pipeline_kiq',
                new=AsyncMock(),
            ),
        ):
            await execute_stage_impl(parent_exec_id)

        advance_calls: list[str] = []

        async def record_advance(rid: str) -> None:
            advance_calls.append(rid)

        with patch(
            'server.apps.pipelines.services.executor.advance_pipeline_kiq',
            side_effect=record_advance,
        ):
            for cid in child_ids:
                await execute_stage_impl(cid)

        parent = await StageExecution.objects.aget(id=parent_exec_id)
        assert parent.status == StageStatus.SUCCEEDED
        assert len(advance_calls) >= 1

    _run(_inner())
