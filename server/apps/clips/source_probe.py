"""Metadata probing for clip sources."""

from typing import Any

from server.common.youtube_metadata import (
    extract_youtube_video_id,
    fetch_youtube_metadata,
)
from server.common.yt_dlp import build_yt_dlp_opts


def probe_youtube_or_rss(url: str) -> dict[str, Any]:
    """Extract title and duration via YouTube API or yt-dlp."""
    if extract_youtube_video_id(url):
        api_info = fetch_youtube_metadata(url)
        if api_info is not None:
            return api_info

    import yt_dlp  # noqa: PLC0415

    ydl_opts = build_yt_dlp_opts(skip_download=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        'title': str(info.get('title', '')),
        'duration_sec': float(info.get('duration') or 0),
    }
