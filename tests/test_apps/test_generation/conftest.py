"""Shared fixtures for generation client tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest


@asynccontextmanager
async def _noop_elevenlabs_slot() -> AsyncIterator[None]:
    yield


@pytest.fixture(autouse=True)
def _bypass_elevenlabs_concurrency() -> None:
    """Skip Redis slot acquisition in ElevenLabs HTTP client unit tests."""
    with patch(
        'server.apps.generation.clients.elevenlabs.elevenlabs_slot',
        _noop_elevenlabs_slot,
    ):
        yield
