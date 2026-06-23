"""Tests for ClipDistributeStage."""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

from server.apps.pipelines.stages.clip_distribute import ClipDistributeStage


def test_clip_distribute_attributes() -> None:
    assert ClipDistributeStage.key == 'clip_distribute'
    assert ClipDistributeStage.queue == 'api'
    assert ClipDistributeStage.max_retries == 2
    assert ClipDistributeStage.timeout_s == 600


def test_clip_distribute_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_distribute' in STAGE_REGISTRY


def test_clip_distribute_fan_out_no_posts() -> None:
    ctx = MagicMock()

    with (
        patch('server.apps.clips.models.ClipPost') as mock_post_cls,
        patch('server.apps.clips.logic.constants.PostStatus'),
    ):
        mock_post_cls.objects.filter.return_value.values.return_value = []
        result = ClipDistributeStage().fan_out(ctx)

    assert result is None


def test_clip_distribute_fan_out_with_posts() -> None:
    ctx = MagicMock()
    post_id = uuid.uuid4()

    with (
        patch('server.apps.clips.models.ClipPost') as mock_post_cls,
        patch('server.apps.clips.logic.constants.PostStatus'),
    ):
        mock_post_cls.objects.filter.return_value.values.return_value = [
            {'id': post_id},
        ]
        result = ClipDistributeStage().fan_out(ctx)

    assert result is not None
    assert len(result) == 1
    assert result[0] == {'post_id': str(post_id)}


def test_clip_distribute_run_with_post_id() -> None:
    ctx = MagicMock()
    ctx.execution.input_snapshot = {'post_id': 'some-post-uuid'}

    async def _inner() -> dict:
        return await ClipDistributeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['post_id'] == 'some-post-uuid'
    assert result['status'] == 'skipped_stub'


def test_clip_distribute_run_no_post_id() -> None:
    ctx = MagicMock()
    ctx.execution.input_snapshot = {}

    async def _inner() -> dict:
        return await ClipDistributeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['post_id'] == ''
    assert result['status'] == 'skipped_stub'
