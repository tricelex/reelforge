"""Tests for the YouTube Analytics API client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.generation.clients.youtube_analytics import fetch_video_report


def test_fetch_video_report_parses_summary_and_retention() -> None:
    summary_resp = MagicMock()
    summary_resp.status_code = 200
    summary_resp.json.return_value = {
        'columnHeaders': [
            {'name': 'views'},
            {'name': 'averageViewDuration'},
            {'name': 'averageViewPercentage'},
        ],
        'rows': [[1000, 245.5, 62.3]],
    }
    retention_resp = MagicMock()
    retention_resp.status_code = 200
    retention_resp.json.return_value = {
        'columnHeaders': [
            {'name': 'elapsedVideoTimeRatio'},
            {'name': 'audienceWatchRatio'},
            {'name': 'relativeRetentionPerformance'},
        ],
        'rows': [[0.01, 0.98, 0.55], [0.5, 0.6, 0.4]],
    }
    impressions_resp = MagicMock()
    impressions_resp.status_code = 200
    impressions_resp.json.return_value = {
        'columnHeaders': [
            {'name': 'impressions'},
            {'name': 'impressionsClickThroughRate'},
        ],
        'rows': [[5000, 4.5]],
    }

    async def _inner() -> dict:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(
                side_effect=[summary_resp, retention_resp, impressions_resp],
            ),
        ):
            return await fetch_video_report(
                access_token='tok',
                channel_youtube_id='UC123',
                video_id='vid1',
            )

    result = asyncio.run(_inner())
    assert result['views'] == 1000
    assert result['avg_view_duration_s'] == 245.5
    assert result['avg_view_percentage'] == 62.3
    assert result['impressions'] == 5000
    assert result['impressions_ctr'] == 4.5
    assert result['retention_curve'] == [
        {
            'elapsed_ratio': 0.01,
            'watch_ratio': 0.98,
            'relative_performance': 0.55,
        },
        {'elapsed_ratio': 0.5, 'watch_ratio': 0.6, 'relative_performance': 0.4},
    ]


def test_fetch_video_report_handles_empty_rows() -> None:
    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {'columnHeaders': [], 'rows': []}

    async def _inner() -> dict:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=empty_resp),
        ):
            return await fetch_video_report(
                access_token='tok',
                channel_youtube_id='UC123',
                video_id='vid1',
            )

    result = asyncio.run(_inner())
    assert result['views'] == 0
    assert result['retention_curve'] == []
    assert result['impressions'] is None
    assert result['impressions_ctr'] is None


def test_fetch_video_report_tolerates_missing_impressions() -> None:
    """A provider error on the impressions query leaves CTR null, not fatal."""
    summary_resp = MagicMock()
    summary_resp.status_code = 200
    summary_resp.json.return_value = {'columnHeaders': [], 'rows': []}
    retention_resp = MagicMock()
    retention_resp.status_code = 200
    retention_resp.json.return_value = {'columnHeaders': [], 'rows': []}
    impressions_resp = MagicMock()
    impressions_resp.status_code = 400
    impressions_resp.text = 'impressions unavailable'

    async def _inner() -> dict:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(
                side_effect=[summary_resp, retention_resp, impressions_resp],
            ),
        ):
            return await fetch_video_report(
                access_token='tok',
                channel_youtube_id='UC123',
                video_id='vid1',
            )

    result = asyncio.run(_inner())
    assert result['impressions'] is None
    assert result['impressions_ctr'] is None


def test_classify_response_raises_retryable() -> None:
    import pytest

    from server.apps.generation.clients.youtube_analytics import (
        _classify_response,
    )
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.status_code = 500
    with pytest.raises(RetryableProviderError):
        _classify_response(resp)


def test_classify_response_raises_fatal() -> None:
    import pytest

    from server.apps.generation.clients.youtube_analytics import (
        _classify_response,
    )
    from server.common.exceptions import FatalProviderError

    resp = MagicMock()
    resp.status_code = 401
    resp.text = 'unauthorized'
    with pytest.raises(FatalProviderError):
        _classify_response(resp)
