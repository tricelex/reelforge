"""Shared yt-dlp option helpers."""

import tempfile
from pathlib import Path
from typing import Any

import structlog
from django.conf import settings

_logger = structlog.get_logger(__name__)

_COOKIE_CACHE_PATH: Path | None = None
_COOKIE_CACHE_KEY: str | None = None


def _materialize_cookie_content(content: str, cache_key: str) -> str:
    """Write cookie content to a writable process-local temp file."""
    global _COOKIE_CACHE_PATH, _COOKIE_CACHE_KEY  # noqa: PLW0603
    if (
        _COOKIE_CACHE_PATH is not None
        and _COOKIE_CACHE_PATH.is_file()
        and cache_key == _COOKIE_CACHE_KEY
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


class _StructlogYtDlpLogger:
    """Routes yt-dlp's internal logger calls into structlog.

    yt-dlp's own `to_screen`/`report_warning`/`report_error` check for a
    configured `logger` before honoring `quiet`/`no_warnings`, so this is
    the only way to see PO token provider diagnostics (e.g. bgutil-provider
    unreachable, PO token rejected) without dropping `quiet` entirely.
    """

    def debug(self, message: str) -> None:
        _logger.debug('yt_dlp', message=message)

    def info(self, message: str) -> None:
        _logger.info('yt_dlp', message=message)

    def warning(self, message: str) -> None:
        _logger.warning('yt_dlp', message=message)

    def error(self, message: str) -> None:
        _logger.error('yt_dlp', message=message)


def build_yt_dlp_opts(**overrides: Any) -> dict[str, Any]:
    """Build yt-dlp options with shared auth and extractor defaults."""
    extractor_args: dict[str, dict[str, list[str]]] = {
        # mweb is the client yt-dlp's PO Token Guide recommends: it only
        # needs a PO token for GVS (video/audio URLs), unlike web (also
        # needs one for subs) or android/ios (no PO token provider support).
        'youtube': {'player_client': ['mweb']},
    }
    pot_base_url = getattr(settings, 'YTDLP_POT_PROVIDER_BASE_URL', '')
    if pot_base_url:
        extractor_args['youtubepot-bgutilhttp'] = {'base_url': [pot_base_url]}

    opts: dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'logger': _StructlogYtDlpLogger(),
        'extractor_args': extractor_args,
    }
    cookie_file = resolve_yt_dlp_cookie_file()
    if cookie_file:
        opts['cookiefile'] = cookie_file
    opts.update(overrides)
    return opts
