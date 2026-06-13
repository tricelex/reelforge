import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_publish_pipeline_event_calls_redis_publish() -> None:
    from server.apps.core.redis_client import publish_pipeline_event

    mock_redis = AsyncMock()

    async def _inner() -> None:
        with patch('server.apps.core.redis_client.get_redis', return_value=mock_redis):
            await publish_pipeline_event('run-abc', b'{"type":"stage.queued"}')
        mock_redis.publish.assert_awaited_once_with(
            'pipeline:run-abc', b'{"type":"stage.queued"}'
        )

    _run(_inner())
