"""Tests for YouTube metadata helpers."""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from server.common.youtube_metadata import (
    extract_youtube_video_id,
    fetch_youtube_metadata,
)


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://www.youtube.com/watch?v=A9Xq3FGjpZA', 'A9Xq3FGjpZA'),
        ('https://youtu.be/A9Xq3FGjpZA', 'A9Xq3FGjpZA'),
        ('https://www.youtube.com/shorts/A9Xq3FGjpZA', 'A9Xq3FGjpZA'),
        ('https://example.com/watch?v=abc', None),
    ],
)
def test_extract_youtube_video_id(url: str, expected: str | None) -> None:
    """YouTube URLs are parsed and other hosts are ignored."""
    assert extract_youtube_video_id(url) == expected


@pytest.mark.django_db
def test_fetch_youtube_metadata_without_api_key() -> None:
    """Missing API key disables metadata fetch."""
    with override_settings(YOUTUBE_DATA_API_KEY=''):
        assert (
            fetch_youtube_metadata(
                'https://www.youtube.com/watch?v=A9Xq3FGjpZA',
            )
            is None
        )


@pytest.mark.django_db
def test_fetch_youtube_metadata_success() -> None:
    """YouTube Data API response is mapped to probe fields."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'items': [
            {
                'snippet': {'title': 'Probe Title'},
                'contentDetails': {'duration': 'PT1M30S'},
            },
        ],
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.get.return_value = mock_response

    with (
        override_settings(YOUTUBE_DATA_API_KEY='test-key'),
        patch('server.common.youtube_metadata.httpx.Client', return_value=mock_client),
    ):
        info = fetch_youtube_metadata(
            'https://www.youtube.com/watch?v=A9Xq3FGjpZA',
        )

    assert info == {'title': 'Probe Title', 'duration_sec': 90.0}
