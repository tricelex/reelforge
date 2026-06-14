import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_get_redis_calls_from_url() -> None:
    from unittest.mock import MagicMock, patch

    from server.common.redis_client import get_redis

    mock_client = MagicMock()
    with patch('redis.asyncio.from_url', return_value=mock_client) as mock_from_url:
        result = get_redis()
    assert result is mock_client
    mock_from_url.assert_called_once()


def test_publish_pipeline_event_calls_redis_publish() -> None:
    from server.common.redis_client import publish_pipeline_event

    mock_redis = AsyncMock()

    async def _inner() -> None:
        with patch('server.common.redis_client.get_redis', return_value=mock_redis):
            await publish_pipeline_event('run-abc', b'{"type":"stage.queued"}')
        mock_redis.publish.assert_awaited_once_with(
            'pipeline:run-abc', b'{"type":"stage.queued"}',
        )

    _run(_inner())
