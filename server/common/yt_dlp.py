"""Shared yt-dlp option helpers."""

import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings

_COOKIE_CACHE_PATH: Path | None = None
_COOKIE_CACHE_KEY: str | None = None


def _materialize_cookie_content(content: str, cache_key: str) -> str:
    """Write cookie content to a writable process-local temp file."""
    global _COOKIE_CACHE_PATH, _COOKIE_CACHE_KEY  # noqa: PLW0603
    if (
        _COOKIE_CACHE_PATH is not None
        and _COOKIE_CACHE_PATH.is_file()
        and _COOKIE_CACHE_KEY == cache_key
    ):
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
    _COOKIE_CACHE_KEY = cache_key
    return str(path)


def resolve_yt_dlp_cookie_file() -> str | None:
    """Return a writable cookie file path when configured and available."""
    configured = getattr(settings, 'YTDLP_COOKIE_FILE', '')
    if configured:
        path = Path(configured)
        if path.is_file():
            content = path.read_text(encoding='utf-8')
            cache_key = f'file:{path}:{path.stat().st_mtime_ns}'
            return _materialize_cookie_content(content, cache_key)

    netscape = getattr(settings, 'YTDLP_COOKIES_NETSCAPE', '')
    if netscape.strip():
        return _materialize_cookie_content(netscape, f'env:{hash(netscape)}')
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
