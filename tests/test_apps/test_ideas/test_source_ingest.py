"""Tests for YouTube source ingestion."""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.ideas.source_ingest import (
    _fetch_caption_text,
    _is_youtube_url,
    _pick_en_track,
    _strip_vtt,
    ingest_youtube,
)


def test_is_youtube_url_accepts_known_hosts() -> None:
    """YouTube hostnames are accepted."""
    assert _is_youtube_url('https://www.youtube.com/watch?v=abc')
    assert _is_youtube_url('https://youtu.be/abc')


def test_is_youtube_url_rejects_other_hosts() -> None:
    """Non-YouTube URLs are rejected."""
    assert not _is_youtube_url('https://example.com/watch?v=abc')
    assert not _is_youtube_url('ftp://youtube.com/x')


def test_strip_vtt_removes_timestamps_and_tags() -> None:
    """VTT markup is stripped to plain text."""
    raw = (
        'WEBVTT\n\n'
        '1\n'
        '00:00:01.000 --> 00:00:03.000\n'
        '<c>Hello</c> world\n'
    )
    assert _strip_vtt(raw) == 'Hello world'


def test_pick_en_track_prefers_english() -> None:
    """English subtitle track is selected when available."""
    tracks = {
        'de': [{'url': 'https://example.com/de'}],
        'en': [{'url': 'https://example.com/en', 'ext': 'vtt'}],
    }
    picked = _pick_en_track(tracks)
    assert picked is not None
    assert picked[0]['ext'] == 'vtt'


def test_fetch_caption_text_downloads_vtt() -> None:
    """Caption URL content is fetched and cleaned."""
    info: dict[str, Any] = {
        'automatic_captions': {
            'en': [{'url': 'https://example.com/cap.vtt', 'ext': 'vtt'}],
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = (
        b'WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello\n'
    )
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch('server.apps.ideas.source_ingest.urllib.request.urlopen', return_value=mock_resp):
        text = _fetch_caption_text(info)

    assert text == 'Hello'


def test_ingest_youtube_builds_snapshot() -> None:
    """Happy path maps yt-dlp info into SourceSnapshot."""
    info: dict[str, Any] = {
        'id': 'abc123',
        'title': 'Viral Video',
        'description': 'A great video',
        'uploader': 'History Hub',
        'duration': 120,
        'view_count': 5000,
    }

    with (
        patch(
            'server.apps.ideas.source_ingest._extract_info',
            return_value=info,
        ),
        patch(
            'server.apps.ideas.source_ingest._fetch_caption_text',
            return_value='caption text',
        ),
    ):
        snapshot = ingest_youtube('https://youtu.be/abc123')

    assert snapshot.video_id == 'abc123'
    assert snapshot.title == 'Viral Video'
    assert snapshot.caption_text == 'caption text'


def test_ingest_youtube_falls_back_to_description() -> None:
    """Description is used when captions are unavailable."""
    info: dict[str, Any] = {
        'id': 'abc123',
        'title': 'No captions',
        'description': 'Fallback description text',
        'uploader': 'Channel',
        'duration': 60,
        'view_count': None,
    }

    with (
        patch(
            'server.apps.ideas.source_ingest._extract_info',
            return_value=info,
        ),
        patch(
            'server.apps.ideas.source_ingest._fetch_caption_text',
            return_value='',
        ),
    ):
        snapshot = ingest_youtube('https://www.youtube.com/watch?v=abc123')

    assert snapshot.caption_text == 'Fallback description text'


def test_strip_vtt_keeps_multiple_spoken_lines() -> None:
    """Multiple spoken lines are joined into one caption string."""
    raw = (
        'WEBVTT\n\n'
        '1\n'
        '00:00:01.000 --> 00:00:02.000\n'
        'First line\n'
        '2\n'
        '00:00:02.000 --> 00:00:03.000\n'
        'Second line\n'
    )
    assert _strip_vtt(raw) == 'First line Second line'


def test_strip_vtt_skips_tag_only_lines() -> None:
    """Lines that clean to empty strings are omitted."""
    raw = 'WEBVTT\n\n<c></c>\nHello'
    assert _strip_vtt(raw) == 'Hello'


def test_fetch_caption_text_returns_empty_without_tracks() -> None:
    """No subtitle tracks yields empty caption text."""
    assert _fetch_caption_text({}) == ''


def test_fetch_caption_text_returns_empty_without_url() -> None:
    """Subtitle track without URL yields empty caption text."""
    info: dict[str, Any] = {
        'subtitles': {'en': [{'ext': 'vtt'}]},
    }
    assert _fetch_caption_text(info) == ''


def test_pick_en_track_returns_none_for_missing_language() -> None:
    """Unknown languages return no track."""
    assert _pick_en_track({'de': [{'url': 'x'}]}) is None
    assert _pick_en_track(None) is None


def test_skip_vtt_line_filters_metadata_rows() -> None:
    """VTT metadata rows are skipped during stripping."""
    from server.apps.ideas.source_ingest import _skip_vtt_line

    assert _skip_vtt_line('WEBVTT')
    assert _skip_vtt_line('12')
    assert _skip_vtt_line('00:00:01.000 --> 00:00:02.000')
    assert _skip_vtt_line('NOTE comment')
    assert not _skip_vtt_line('spoken words')


def test_extract_info_raises_when_missing() -> None:
    """Missing yt-dlp metadata raises ValidationError."""
    fake_yt = MagicMock()
    fake_yt.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = None
    with patch.dict(sys.modules, {'yt_dlp': fake_yt}):
        from server.apps.ideas.source_ingest import _extract_info

        with pytest.raises(ValidationError, match='Could not extract'):
            _extract_info('https://youtu.be/missing')


def test_extract_info_returns_metadata() -> None:
    """yt-dlp metadata dict is returned on success."""
    payload: dict[str, Any] = {'id': 'abc', 'title': 'T'}
    fake_yt = MagicMock()
    fake_yt.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = payload
    with patch.dict(sys.modules, {'yt_dlp': fake_yt}):
        from server.apps.ideas.source_ingest import _extract_info

        assert _extract_info('https://youtu.be/abc') == payload
