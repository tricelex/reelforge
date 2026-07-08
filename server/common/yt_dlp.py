"""Shared yt-dlp option helpers."""

import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings

_COOKIE_CACHE_PATH: Path | None = None


def _materialize_netscape_cookies(content: str) -> str:
    """Write Netscape cookie content to a process-local temp file."""
    global _COOKIE_CACHE_PATH  # noqa: PLW0603
    if _COOKIE_CACHE_PATH is not None and _COOKIE_CACHE_PATH.is_file():
        return str(_COOKIE_CACHE_PATH)

    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        prefix='ytdlp-cookies-',
        suffix='.txt',
        delete=False,
    ) as handle:
        handle.write(content)
        path = Path(handle.name)
    _COOKIE_CACHE_PATH = path
    return str(path)


def resolve_yt_dlp_cookie_file() -> str | None:
    """Return a cookie file path when configured and available."""
    configured = getattr(settings, 'YTDLP_COOKIE_FILE', '')
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)

    netscape = getattr(settings, 'YTDLP_COOKIES_NETSCAPE', '')
    if netscape.strip():
        return _materialize_netscape_cookies(netscape)
    return None


def build_yt_dlp_opts(**overrides: Any) -> dict[str, Any]:
    """Build yt-dlp options with shared auth and extractor defaults."""
    opts: dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            },
        },
    }
    cookie_file = resolve_yt_dlp_cookie_file()
    if cookie_file:
        opts['cookiefile'] = cookie_file
    opts.update(overrides)
    return opts
