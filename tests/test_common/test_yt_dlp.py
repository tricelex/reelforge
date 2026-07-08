"""Tests for shared yt-dlp helpers."""

from pathlib import Path

import pytest
import structlog.testing
from django.test import override_settings

from server.common.yt_dlp import (
    _StructlogYtDlpLogger,
    build_yt_dlp_opts,
    resolve_yt_dlp_cookie_file,
)


@pytest.mark.django_db
def test_build_yt_dlp_opts_without_cookies() -> None:
    """Default opts use the mweb client and no cookie file."""
    with override_settings(
        YTDLP_COOKIE_FILE='',
        YTDLP_COOKIES_NETSCAPE='',
        YTDLP_POT_PROVIDER_BASE_URL='',
    ):
        opts = build_yt_dlp_opts(skip_download=True)
    assert opts['skip_download'] is True
    assert 'cookiefile' not in opts
    assert opts['extractor_args']['youtube']['player_client'] == ['mweb']
    assert 'youtubepot-bgutilhttp' not in opts['extractor_args']


@pytest.mark.django_db
def test_build_yt_dlp_opts_routes_logging_through_structlog() -> None:
    """A structlog-backed logger is wired up regardless of quiet/no_warnings.

    yt-dlp only honors quiet/no_warnings when no logger is configured, so
    without this, PO token provider diagnostics (e.g. bgutil-provider
    unreachable) would be silently dropped instead of reaching structlog.
    """
    opts = build_yt_dlp_opts()
    assert opts['quiet'] is True
    assert opts['no_warnings'] is True
    assert isinstance(opts['logger'], _StructlogYtDlpLogger)


@pytest.mark.django_db
def test_build_yt_dlp_opts_with_pot_provider() -> None:
    """Configured PO token provider base URL is passed to yt-dlp."""
    with override_settings(
        YTDLP_POT_PROVIDER_BASE_URL='http://bgutil-provider:4416',
    ):
        opts = build_yt_dlp_opts()
    assert opts['extractor_args']['youtubepot-bgutilhttp'] == {
        'base_url': ['http://bgutil-provider:4416'],
    }


@pytest.mark.django_db
def test_build_yt_dlp_opts_without_pot_provider() -> None:
    """Empty PO token provider base URL omits the extractor arg."""
    with override_settings(YTDLP_POT_PROVIDER_BASE_URL=''):
        opts = build_yt_dlp_opts()
    assert 'youtubepot-bgutilhttp' not in opts['extractor_args']


def test_structlog_ytdlp_logger_forwards_all_levels() -> None:
    """Each yt-dlp logger method forwards to structlog without error."""
    logger = _StructlogYtDlpLogger()
    logger.debug('debug message')
    logger.info('info message')
    logger.warning('warning message')
    logger.error('error message')


def test_structlog_ytdlp_logger_debug_logs_at_info_level() -> None:
    """debug() logs at info, since the 'server' namespace runs at INFO.

    yt-dlp's own PO token/playability diagnostics are emitted via
    `to_screen` (routed to our `debug()`), so logging them at debug would
    have them silently dropped before reaching Logfire in production.
    """
    with structlog.testing.capture_logs() as captured:
        _StructlogYtDlpLogger().debug('[debug] some diagnostic')
    assert captured == [
        {
            'event': 'yt_dlp',
            'message': '[debug] some diagnostic',
            'log_level': 'info',
        },
    ]


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_from_path(tmp_path: Path) -> None:
    """Configured cookie file path is copied to a writable temp file."""
    cookie_path = tmp_path / 'cookies.txt'
    cookie_path.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
    with override_settings(
        YTDLP_COOKIE_FILE=str(cookie_path),
        YTDLP_COOKIES_NETSCAPE='',
    ):
        resolved = resolve_yt_dlp_cookie_file()
    assert resolved is not None
    assert resolved != str(cookie_path)
    assert Path(resolved).is_file()


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_from_netscape_content() -> None:
    """Netscape cookie content is materialized to a temp file."""
    content = (
        '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tx\ty\n'
    )
    with override_settings(
        YTDLP_COOKIE_FILE='',
        YTDLP_COOKIES_NETSCAPE=content,
    ):
        path = resolve_yt_dlp_cookie_file()
    assert path is not None
    assert Path(path).is_file()
    assert Path(path).read_text(encoding='utf-8') == content


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_missing_path() -> None:
    """Missing cookie file path returns None."""
    with override_settings(
        YTDLP_COOKIE_FILE='/tmp/does-not-exist-cookies.txt',
        YTDLP_COOKIES_NETSCAPE='',
    ):
        assert resolve_yt_dlp_cookie_file() is None
