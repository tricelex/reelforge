"""YouTube metadata via Data API v3 (no yt-dlp cookies required)."""

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from django.conf import settings

_YOUTUBE_HOSTS = frozenset({
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
})
_ISO8601_DURATION_RE = re.compile(
    r'^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$',
)
_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'


def _video_id_from_youtu_be(path: str) -> str | None:
    video_id = path.lstrip('/').split('/')[0]
    return video_id or None


def _video_id_from_watch_query(query: str) -> str | None:
    query_ids = parse_qs(query).get('v', [])
    return query_ids[0] if query_ids else None


def _video_id_from_prefixed_path(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    video_id = path.removeprefix(prefix).split('/')[0]
    return video_id or None


def _video_id_from_youtube_path(host: str, path: str, query: str) -> str | None:
    if host.endswith('youtu.be'):
        return _video_id_from_youtu_be(path)
    if path == '/watch':
        return _video_id_from_watch_query(query)
    for prefix in ('/embed/', '/shorts/', '/live/'):
        video_id = _video_id_from_prefixed_path(path, prefix)
        if video_id is not None:
            return video_id
    return None


def extract_youtube_video_id(url: str) -> str | None:
    """Extract a YouTube video ID from a URL, or None when not YouTube."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {'http', 'https'}:
        return None
    host = (parsed.hostname or '').lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    return _video_id_from_youtube_path(host, parsed.path, parsed.query)


def _parse_iso8601_duration(value: str) -> float:
    match = _ISO8601_DURATION_RE.fullmatch(value)
    if match is None:
        return 0.0
    groups = match.groupdict(default='0')
    hours = int(groups['hours'])
    minutes = int(groups['minutes'])
    seconds = int(groups['seconds'])
    return float(hours * 3600 + minutes * 60 + seconds)


def fetch_youtube_metadata(url: str) -> dict[str, Any] | None:
    """Fetch title and duration via YouTube Data API when configured."""
    api_key = getattr(settings, 'YOUTUBE_DATA_API_KEY', '')
    if not api_key:
        return None

    video_id = extract_youtube_video_id(url)
    if not video_id:
        return None

    with httpx.Client(timeout=30) as client:
        response = client.get(
            _VIDEOS_URL,
            params={
                'part': 'snippet,contentDetails',
                'id': video_id,
                'key': api_key,
            },
        )
    if response.status_code != 200:
        return None

    items = response.json().get('items', [])
    if not items:
        return None

    item = items[0]
    snippet = item.get('snippet', {})
    content_details = item.get('contentDetails', {})
    duration_raw = str(content_details.get('duration', ''))
    return {
        'title': str(snippet.get('title', '')),
        'duration_sec': _parse_iso8601_duration(duration_raw),
    }
