"""Tests for the Pexels footage adapter.

WARNING: fixtures are doc-derived, not captured from a live API. Re-verify
this adapter against a real response once PEXELS_API_KEY is configured.
Field mapping is documented in `pexels.py`.
"""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.pexels import PexelsProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((_FIXTURES / name).read_text()))


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.anyio
async def test_video_search_maps_candidates() -> None:
    """Each video result becomes a well-formed FootageCandidate."""
    payload = _load('pexels_video_search.json')
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await PexelsProvider(api_key='k').search(
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'pexels'
        assert candidate.media_type == 'video'
        assert candidate.download_url.startswith('http')
        assert candidate.thumb_url.startswith('http')
        assert candidate.width > 0
        assert candidate.duration_s is not None
        assert candidate.attribution_required is False
        assert candidate.license == 'pexels'


@pytest.mark.anyio
async def test_photo_search_maps_candidates() -> None:
    """Photo results map to image candidates with no duration."""
    payload = _load('pexels_photo_search.json')
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await PexelsProvider(api_key='k').search(
            'ocean waves',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.media_type == 'image'
        assert candidate.duration_s is None


@pytest.mark.anyio
async def test_rate_limit_raises_retryable() -> None:
    """HTTP 429 surfaces as RetryableProviderError with the status code."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 429
    resp.text = 'rate limited'
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError) as exc_info:
            await PexelsProvider(api_key='k').search(
                'x',
                media_type='video',
                orientation='landscape',
                min_width=1280,
                limit=3,
            )
    assert exc_info.value.status_code == 429
    assert exc_info.value.provider == 'pexels'


@pytest.mark.anyio
async def test_missing_api_key_returns_no_candidates() -> None:
    """An unconfigured provider is skipped, not an error."""
    results = await PexelsProvider(api_key='').search(
        'x',
        media_type='video',
        orientation='landscape',
        min_width=1280,
        limit=3,
    )
    assert results == []
