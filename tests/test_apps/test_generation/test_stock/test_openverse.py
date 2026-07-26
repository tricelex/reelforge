"""Tests for the Openverse adapter.

Fixture captured from https://api.openverse.org/v1/ on the date this module
was added. See openverse.py for the media-type support finding.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.openverse import OpenverseProvider
from server.common.exceptions import RetryableProviderError

_FIXTURES = Path(__file__).parent / 'fixtures'


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.anyio
async def test_image_search_maps_candidates() -> None:
    """CC-licensed image results map with licence and creator populated."""
    payload = json.loads(
        (_FIXTURES / 'openverse_image_search.json').read_text(),
    )
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await OpenverseProvider(token='').search(
            'battleship',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'openverse'
        assert candidate.media_type == 'image'
        assert candidate.license
        assert candidate.source_page_url.startswith('http')
    assert results[0].license == 'by-nc-nd-2.0'


@pytest.mark.anyio
async def test_public_domain_does_not_require_attribution() -> None:
    """CC0/PDM candidates are flagged as attribution-optional."""
    payload: dict[str, object] = {
        'results': [
            {
                'id': 'abc',
                'title': 'A public domain photo',
                'url': 'https://example.test/full.jpg',
                'thumbnail': 'https://example.test/thumb.jpg',
                'foreign_landing_url': 'https://example.test/page',
                'width': 2000,
                'height': 1400,
                'license': 'cc0',
                'license_version': '1.0',
                'license_url': (
                    'https://creativecommons.org/publicdomain/zero/1.0/'
                ),
                'creator': 'Someone',
            },
        ],
    }
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await OpenverseProvider(token='').search(
            'x',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results[0].attribution_required is False


@pytest.mark.anyio
async def test_by_license_requires_attribution() -> None:
    """CC-BY family candidates require attribution."""
    payload: dict[str, object] = {
        'results': [
            {
                'id': 'def',
                'title': 'A CC-BY photo',
                'url': 'https://example.test/full.jpg',
                'thumbnail': 'https://example.test/thumb.jpg',
                'foreign_landing_url': 'https://example.test/page',
                'width': 2000,
                'height': 1400,
                'license': 'by-sa',
                'license_version': '4.0',
                'license_url': (
                    'https://creativecommons.org/licenses/by-sa/4.0/'
                ),
                'creator': 'Someone',
            },
        ],
    }
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await OpenverseProvider(token='').search(
            'x',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results[0].attribution_required is True


@pytest.mark.anyio
async def test_video_media_type_returns_empty() -> None:
    """Openverse indexes no video; the provider declines rather than fails."""
    results = await OpenverseProvider(token='').search(
        'x',
        media_type='video',
        orientation='landscape',
        min_width=1280,
        limit=3,
    )
    assert results == []


@pytest.mark.anyio
async def test_server_error_raises_retryable() -> None:
    """An unsuccessful image search preserves provider and status."""
    response = MagicMock()
    response.is_success = False
    response.status_code = 503
    response.text = 'unavailable'

    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=response),
    ):
        search = OpenverseProvider(token='token').search(
            'x',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
        with pytest.raises(RetryableProviderError) as exc_info:
            await search

    assert exc_info.value.provider == 'openverse'
    assert exc_info.value.status_code == 503
