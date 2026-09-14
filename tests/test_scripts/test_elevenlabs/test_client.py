"""Tests for scripts/elevenlabs/client.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.elevenlabs.client import force_align, synthesize


def test_synthesize_returns_audio_bytes_on_success() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'fake-mp3-data'

    async def _inner() -> bytes:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await synthesize(
                text='Hello world',
                voice_id='xyz',
                api_key='key',
            )

    assert asyncio.run(_inner()) == b'fake-mp3-data'


def test_synthesize_sends_v3_model_by_default() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'audio'

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ) as mock_post:
            await synthesize(text='Hi', voice_id='xyz', api_key='key')
            _, kwargs = mock_post.call_args
            return kwargs['json']

    body = asyncio.run(_inner())
    assert body['model_id'] == 'eleven_v3'


def test_synthesize_raises_runtime_error_on_failure() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 422
    mock_resp.text = 'invalid voice_id'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await synthesize(text='Hi', voice_id='bad', api_key='key')

    with pytest.raises(RuntimeError, match='422'):
        asyncio.run(_inner())


def test_force_align_returns_parsed_json_on_success() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'words': [{'text': 'Hi', 'start': 0.0, 'end': 0.3}],
    }

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await force_align(
                audio_bytes=b'fake-audio',
                text='Hi',
                api_key='key',
            )

    result = asyncio.run(_inner())
    assert result == {'words': [{'text': 'Hi', 'start': 0.0, 'end': 0.3}]}


def test_force_align_raises_runtime_error_on_failure() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 500
    mock_resp.text = 'server error'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await force_align(audio_bytes=b'x', text='Hi', api_key='key')

    with pytest.raises(RuntimeError, match='500'):
        asyncio.run(_inner())
