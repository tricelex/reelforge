"""Metadata probing for clip sources."""

from typing import Any


def probe_youtube_or_rss(url: str) -> dict[str, Any]:
    """Extract title and duration via yt-dlp without downloading."""
    import yt_dlp  # noqa: PLC0415

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        'title': str(info.get('title', '')),
        'duration_sec': float(info.get('duration') or 0),
    }
