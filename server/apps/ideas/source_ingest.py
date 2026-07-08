"""Ingest external sources for remix ideation (YouTube MVP)."""

import re
import urllib.request
from typing import Any, cast
from urllib.parse import urlparse

from django.core.exceptions import ValidationError

from server.apps.ideas.logic.schemas import SourceSnapshot
from server.common.yt_dlp import build_yt_dlp_opts

_CAPTION_CHAR_CAP = 4000
_YOUTUBE_HOSTS = frozenset({
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
})
_VTT_TAG_RE = re.compile(r'<[^>]+>')
_VTT_TIMESTAMP_RE = re.compile(
    r'\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}',
)


def _is_youtube_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {'http', 'https'}:
        return False
    host = (parsed.hostname or '').lower()
    return host in _YOUTUBE_HOSTS


def _skip_vtt_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith('WEBVTT'):
        return True
    if stripped.isdigit():
        return True
    if _VTT_TIMESTAMP_RE.search(stripped):
        return True
    return stripped.startswith('NOTE')


def _strip_vtt(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        if _skip_vtt_line(line):
            continue
        cleaned = _VTT_TAG_RE.sub('', line.strip()).strip()
        if cleaned:
            lines.append(cleaned)
    text = ' '.join(lines)
    return text[:_CAPTION_CHAR_CAP]


def _pick_en_track(
    tracks: dict[str, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]] | None:
    if not tracks:
        return None
    for key in ('en', 'en-US', 'en-GB', 'en-us'):
        if key in tracks:
            return tracks[key]
    return None


def _fetch_caption_text(info: dict[str, Any]) -> str:
    tracks = _pick_en_track(info.get('automatic_captions'))
    if tracks is None:
        tracks = _pick_en_track(info.get('subtitles'))
    if not tracks:
        return ''

    vtt_track = next(
        (track for track in tracks if track.get('ext') == 'vtt'),
        tracks[0],
    )
    caption_url = vtt_track.get('url')
    if not caption_url:
        return ''

    with urllib.request.urlopen(caption_url, timeout=30) as resp:  # noqa: S310
        raw = resp.read().decode('utf-8', errors='replace')
    return _strip_vtt(raw)


def _extract_info(url: str) -> dict[str, Any]:
    import yt_dlp  # noqa: PLC0415

    ydl_opts = build_yt_dlp_opts(skip_download=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        raw_info = ydl.extract_info(url, download=False)
    if raw_info is None:
        msg = f'Could not extract source metadata: {url}'
        raise ValidationError(msg)
    return cast('dict[str, Any]', raw_info)


def ingest_youtube(url: str) -> SourceSnapshot:
    """Fetch YouTube metadata and EN captions without downloading video."""
    if not _is_youtube_url(url):
        msg = 'source_url must be a YouTube URL'
        raise ValidationError(msg)

    info = _extract_info(url)
    video_id = str(info.get('id', ''))
    description = str(info.get('description', '') or '')
    caption_text = _fetch_caption_text(info)
    if not caption_text and description:
        caption_text = description[:_CAPTION_CHAR_CAP]

    view_count = info.get('view_count')
    parsed_views = int(view_count) if view_count is not None else None

    return SourceSnapshot(
        url=url.strip(),
        video_id=video_id,
        title=str(info.get('title', '') or 'Untitled video'),
        description=description[:_CAPTION_CHAR_CAP],
        channel=str(info.get('uploader', '') or info.get('channel', '') or ''),
        duration_sec=float(info.get('duration', 0) or 0),
        view_count=parsed_views,
        caption_text=caption_text,
    )
