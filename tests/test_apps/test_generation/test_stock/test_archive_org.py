"""Tests for the Internet Archive archival-video adapter."""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.archive_org import ArchiveOrgProvider
from server.apps.generation.clients.stock.base import FootageCandidate
from server.common.exceptions import RetryableProviderError

_FIXTURES = Path(__file__).parent / 'fixtures'


def _load_fixture() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((_FIXTURES / 'archive_org_search.json').read_text()),
    )


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.is_success = True
    response.status_code = 200
    response.json.return_value = payload
    return response


async def _search_with_responses(
    *responses: MagicMock,
) -> list[FootageCandidate]:
    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(side_effect=responses),
    ):
        return await ArchiveOrgProvider().search(
            'newsreel',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )


@pytest.mark.anyio
async def test_search_maps_playable_mp4_candidate() -> None:
    """A search doc and its first MP4 file become a video candidate."""
    search_payload = _load_fixture()
    metadata_payload: dict[str, object] = {
        'files': [
            {'name': 'poster.jpg'},
            {
                'name': 'Newsreel.mp4',
                'width': '1920',
                'height': '1080',
                'length': '62.5',
            },
            {'name': 'alternate.mp4', 'width': '640', 'height': '360'},
        ],
    }
    response = cast(dict[str, object], search_payload['response'])
    docs = cast(list[dict[str, object]], response['docs'])
    response['docs'] = [docs[1]]

    results = await _search_with_responses(
        _mock_response(search_payload),
        _mock_response(metadata_payload),
    )

    assert len(results) == 1
    candidate = results[0]
    assert candidate.provider == 'archive_org'
    assert candidate.external_id == 'USAF-17134'
    assert candidate.media_type == 'video'
    assert candidate.download_url == (
        'https://archive.org/download/USAF-17134/Newsreel.mp4'
    )
    assert candidate.source_page_url == (
        'https://archive.org/details/USAF-17134'
    )
    assert candidate.width == 1920
    assert candidate.height == 1080
    assert candidate.duration_s == 62.5
    assert candidate.license == 'pdm-1.0'
    assert candidate.attribution_required is False


@pytest.mark.anyio
async def test_missing_license_defaults_to_unknown_and_attribution() -> None:
    """An omitted archive.org license errs toward requiring attribution."""
    search_payload = _load_fixture()
    response = cast(dict[str, object], search_payload['response'])
    docs = cast(list[dict[str, object]], response['docs'])
    response['docs'] = [docs[0]]
    metadata_payload: dict[str, object] = {
        'files': [{'name': 'clip.mp4'}],
    }

    results = await _search_with_responses(
        _mock_response(search_payload),
        _mock_response(metadata_payload),
    )

    assert results[0].license == 'unknown'
    assert results[0].license_url == ''
    assert results[0].attribution_required is True


@pytest.mark.anyio
async def test_empty_search_returns_empty_list() -> None:
    """An empty advanced-search response requires no metadata requests."""
    results = await _search_with_responses(
        _mock_response({'response': {'docs': []}}),
    )
    assert results == []


@pytest.mark.anyio
async def test_item_without_mp4_is_skipped() -> None:
    """Archive items without a playable MP4 are skipped, not crashed."""
    search_payload: dict[str, object] = {
        'response': {'docs': [{'identifier': 'audio-only'}]},
    }
    metadata_payload: dict[str, object] = {
        'files': [{'name': 'recording.ogg'}, {'name': 'cover.jpg'}],
    }

    results = await _search_with_responses(
        _mock_response(search_payload),
        _mock_response(metadata_payload),
    )
    assert results == []


@pytest.mark.anyio
async def test_server_error_raises_retryable() -> None:
    """A 5xx search response preserves provider and status information."""
    response = MagicMock()
    response.is_success = False
    response.status_code = 503
    response.text = 'unavailable'

    with patch(
        'httpx.AsyncClient.get',
        new=AsyncMock(return_value=response),
    ):
        search = ArchiveOrgProvider().search(
            'newsreel',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
        with pytest.raises(RetryableProviderError) as exc_info:
            await search

    assert exc_info.value.provider == 'archive_org'
    assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_image_media_type_returns_empty() -> None:
    """The archival-video provider declines still-image searches."""
    results = await ArchiveOrgProvider().search(
        'newsreel',
        media_type='image',
        orientation='landscape',
        min_width=1280,
        limit=3,
    )
    assert results == []
