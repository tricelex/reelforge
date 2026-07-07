"""Tests for the text embeddings client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.generation.clients.embeddings import embed_text


def test_embed_text_returns_vector_from_openai_response() -> None:
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    async def _inner() -> list[float]:
        with patch(
            'server.apps.generation.clients.embeddings.AsyncOpenAI',
        ) as mock_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client
            return await embed_text('some script text')

    result = asyncio.run(_inner())
    assert result == [0.1, 0.2, 0.3]


def test_embed_text_truncates_long_input() -> None:
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.5])]
    captured: dict = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return fake_response

    async def _inner() -> list[float]:
        with patch(
            'server.apps.generation.clients.embeddings.AsyncOpenAI',
        ) as mock_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create = _fake_create
            mock_cls.return_value = mock_client
            return await embed_text('x' * 20000)

    asyncio.run(_inner())
    assert len(captured['input']) == 8000
