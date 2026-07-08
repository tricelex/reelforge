"""Tests for clip source probing."""

import sys
from unittest.mock import MagicMock, patch

from django.test import override_settings

from server.apps.clips.source_probe import probe_youtube_or_rss


def test_probe_youtube_or_rss_uses_api_for_youtube_urls() -> None:
    """YouTube URLs prefer Data API metadata when configured."""
    with (
        override_settings(YOUTUBE_DATA_API_KEY='test-key'),
        patch(
            'server.apps.clips.source_probe.fetch_youtube_metadata',
            return_value={'title': 'API Title', 'duration_sec': 42.0},
        ) as fetch_mock,
    ):
        info = probe_youtube_or_rss(
            'https://www.youtube.com/watch?v=A9Xq3FGjpZA',
        )
    fetch_mock.assert_called_once_with(
        'https://www.youtube.com/watch?v=A9Xq3FGjpZA',
    )
    assert info == {'title': 'API Title', 'duration_sec': 42.0}


def test_probe_youtube_or_rss_falls_back_to_ytdlp() -> None:
    """Non-YouTube URLs and API misses still use yt-dlp."""
    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = {
        'title': 'RSS Title',
        'duration': 15,
    }
    with (
        override_settings(YOUTUBE_DATA_API_KEY=''),
        patch.dict(sys.modules, {'yt_dlp': mock_ytdlp}),
    ):
        info = probe_youtube_or_rss('https://feeds.example.com/podcast.rss')
    assert info == {'title': 'RSS Title', 'duration_sec': 15.0}
