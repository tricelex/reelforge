"""WARNING: Fixtures are documentation-derived, not live-captured.

Re-verify this adapter against a real response once PIXABAY_API_KEY is
configured. Pixabay licence does not require attribution.
"""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.pixabay import PixabayProvider

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
    """Video hits map to video candidates with a duration."""
    payload = _load('pixabay_video_search.json')
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await PixabayProvider(api_key='k').search(
            'ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert len(results) == 3
    assert results[0].width == 1280
    assert results[0].download_url.endswith('_medium.mp4')
    assert (
        results[0].thumb_url
        == 'https://cdn.pixabay.com/video/2020/04/18/31377-411640780_medium.jpg'
    )
    assert results[1].width == 1920
    assert (
        results[1].thumb_url
        == 'https://cdn.pixabay.com/video/2021/10/08/85734-628344310_medium.jpg'
    )
    assert results[2].width == 960
    assert (
        results[2].thumb_url
        == 'https://cdn.pixabay.com/video/2023/02/01/152001-794211020_small.jpg'
    )
    for candidate in results:
        assert candidate.provider == 'pixabay'
        assert candidate.media_type == 'video'
        assert candidate.duration_s is not None
        assert candidate.attribution_required is False
        assert 'avatar' not in candidate.thumb_url


@pytest.mark.anyio
async def test_photo_search_maps_candidates() -> None:
    """Photo hits map to image candidates with tags populated."""
    payload = _load('pixabay_photo_search.json')
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await PixabayProvider(api_key='k').search(
            'ocean',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    assert all(candidate.media_type == 'image' for candidate in results)
    assert all(candidate.duration_s is None for candidate in results)
    assert results[0].tags == ('ocean', 'sea', 'waves')


@pytest.mark.anyio
async def test_rate_limit_raises_retryable() -> None:
    """HTTP 429 surfaces as RetryableProviderError."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 429
    resp.text = 'rate limited'
    provider = PixabayProvider(api_key='k')
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError) as exc_info:
            await provider.search(
                'x',
                media_type='video',
                orientation='landscape',
                min_width=1280,
                limit=3,
            )
    assert exc_info.value.provider == 'pixabay'
    assert exc_info.value.status_code == 429


@pytest.mark.anyio
async def test_missing_api_key_returns_no_candidates() -> None:
    """An unconfigured provider is skipped, not an error."""
    results = await PixabayProvider(api_key='').search(
        'x',
        media_type='video',
        orientation='landscape',
        min_width=1280,
        limit=3,
    )
    assert results == []
