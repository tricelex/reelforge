"""Tests for ElevenLabs distributed concurrency limiting."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.common.exceptions import RetryableProviderError
    """Redis acquire/release is called when the client connects."""
    from server.apps.generation.clients.elevenlabs_concurrency import (
        elevenlabs_slot,
    )

    async def _inner() -> None:
        with (
            patch(
                'server.apps.generation.clients.elevenlabs_concurrency'
                '._acquire_redis_slot',
                new=AsyncMock(return_value=True),
            ) as acquire,
            patch(
                'server.apps.generation.clients.elevenlabs_concurrency'
                '._release_redis_slot',
                new=AsyncMock(),
            ) as release,
        ):
            async with elevenlabs_slot():
                pass
            acquire.assert_awaited_once()
            release.assert_awaited_once()

    asyncio.run(_inner())


def test_elevenlabs_slot_timeout_raises_retryable() -> None:
    """Slot acquisition timeout surfaces as RetryableProviderError."""
    from server.apps.generation.clients.elevenlabs_concurrency import (
        elevenlabs_slot,
    )

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.elevenlabs_concurrency'
            '._acquire_redis_slot',
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(RetryableProviderError) as exc_info:
                async with elevenlabs_slot():
                    pass
            assert exc_info.value.status_code == 429

    asyncio.run(_inner())


def test_elevenlabs_slot_falls_back_to_local_semaphore() -> None:
    """Redis failures fall back to the in-process semaphore."""
    from server.apps.generation.clients.elevenlabs_concurrency import (
        elevenlabs_slot,
    )

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.elevenlabs_concurrency'
            '._acquire_redis_slot',
            new=AsyncMock(side_effect=ConnectionError('redis down')),
        ):
            async with elevenlabs_slot():
                pass

    asyncio.run(_inner())
