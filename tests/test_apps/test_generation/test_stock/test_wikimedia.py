"""Tests for the Wikimedia Commons adapter.

Fixture captured from the MediaWiki API on the date this module was added.
Licences vary per file and attribution is usually REQUIRED.
"""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.wikimedia import WikimediaProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _load_fixture() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((_FIXTURES / 'wikimedia_search.json').read_text()),
    )


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.anyio
async def test_search_maps_candidates_with_licence_metadata() -> None:
    """Commons results carry licence, author, and a source page."""
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(_load_fixture())),
    ):
        results = await WikimediaProvider().search(
            'battleship',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert len(results) == 3
    for candidate in results:
        assert candidate.provider == 'wikimedia'
        assert candidate.source_page_url.startswith('http')
        assert candidate.license == 'pd'
        assert candidate.license_url == ''
        assert candidate.thumb_url == candidate.download_url


@pytest.mark.anyio
async def test_attribution_required_is_read_from_extmetadata() -> None:
    """AttributionRequired='false' is honoured, not overridden to True."""
    payload: dict[str, object] = {
        'query': {
            'pages': {
                '1': {
                    'pageid': 1,
                    'title': 'File:X.jpg',
                    'imageinfo': [
                        {
                            'url': 'https://upload.test/x.jpg',
                            'descriptionurl': 'https://commons.test/x',
                            'width': 2000,
                            'height': 1400,
                            'extmetadata': {
                                'AttributionRequired': {'value': 'false'},
                                'License': {'value': 'pd'},
                                'Artist': {
                                    'value': '<a href="/x">Someone</a>',
                                },
                            },
                        },
                    ],
                },
            },
        },
    }
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await WikimediaProvider().search(
            'x',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results[0].attribution_required is False
    assert results[0].license == 'pd'
    assert results[0].author == 'Someone'


@pytest.mark.anyio
async def test_absent_attribution_flag_defaults_to_required() -> None:
    """A missing AttributionRequired key errs toward attributing."""
    payload: dict[str, object] = {
        'query': {
            'pages': {
                '1': {
                    'pageid': 1,
                    'title': 'File:Y.jpg',
                    'imageinfo': [
                        {
                            'url': 'https://upload.test/y.jpg',
                            'descriptionurl': 'https://commons.test/y',
                            'width': 2000,
                            'height': 1400,
                            'extmetadata': {
                                'License': {'value': 'cc-by-sa-4.0'},
                            },
                        },
                    ],
                },
            },
        },
    }
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response(payload)),
    ):
        results = await WikimediaProvider().search(
            'y',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results[0].attribution_required is True


@pytest.mark.anyio
async def test_empty_result_set_returns_empty_list() -> None:
    """A search with no matches yields no candidates, not an error."""
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=_mock_response({'batchcomplete': ''})),
    ):
        results = await WikimediaProvider().search(
            'zzzznomatch',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results == []


@pytest.mark.anyio
async def test_server_error_raises_retryable() -> None:
    """A 5xx from Commons is retryable."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 503
    resp.text = 'unavailable'
    provider = WikimediaProvider()
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError) as exc_info:
            await provider.search(
                'x',
                media_type='image',
                orientation='landscape',
                min_width=1280,
                limit=3,
            )
    assert exc_info.value.provider == 'wikimedia'
    assert exc_info.value.status_code == 503
