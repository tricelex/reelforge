"""Tests for shared yt-dlp helpers."""

from pathlib import Path

import pytest
from django.test import override_settings

from server.common.yt_dlp import build_yt_dlp_opts, resolve_yt_dlp_cookie_file


@pytest.mark.django_db
def test_build_yt_dlp_opts_without_cookies() -> None:
    """Default opts include extractor args but no cookie file."""
    with override_settings(YTDLP_COOKIE_FILE='', YTDLP_COOKIES_NETSCAPE=''):
        opts = build_yt_dlp_opts(skip_download=True)
    assert opts['skip_download'] is True
    assert 'cookiefile' not in opts
    assert opts['extractor_args']['youtube']['player_client'] == [
        'android',
        'web',
    ]


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_from_path(tmp_path: Path) -> None:
    """Configured cookie file path is returned when present."""
    cookie_path = tmp_path / 'cookies.txt'
    cookie_path.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
    with override_settings(
        YTDLP_COOKIE_FILE=str(cookie_path),
        YTDLP_COOKIES_NETSCAPE='',
    ):
        assert resolve_yt_dlp_cookie_file() == str(cookie_path)


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_from_netscape_content() -> None:
    """Netscape cookie content is materialized to a temp file."""
    content = '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tx\ty\n'
    with override_settings(
        YTDLP_COOKIE_FILE='',
        YTDLP_COOKIES_NETSCAPE=content,
    ):
        path = resolve_yt_dlp_cookie_file()
    assert path is not None
    assert Path(path).is_file()
    assert Path(path).read_text(encoding='utf-8') == content


@pytest.mark.django_db
def test_build_yt_dlp_opts_uses_cookie_file(tmp_path: Path) -> None:
    """Cookie file path is injected into yt-dlp options."""
    cookie_path = tmp_path / 'cookies.txt'
    cookie_path.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
    with override_settings(
        YTDLP_COOKIE_FILE=str(cookie_path),
        YTDLP_COOKIES_NETSCAPE='',
    ):
        opts = build_yt_dlp_opts()
    assert opts['cookiefile'] == str(cookie_path)
    assert opts['no_cookies_update'] is True


@pytest.mark.django_db
def test_resolve_yt_dlp_cookie_file_missing_path() -> None:
    """Missing cookie file path returns None."""
    with override_settings(
        YTDLP_COOKIE_FILE='/tmp/does-not-exist-cookies.txt',
        YTDLP_COOKIES_NETSCAPE='',
    ):
        assert resolve_yt_dlp_cookie_file() is None
