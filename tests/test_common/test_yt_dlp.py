"""Tests for shared yt-dlp helpers."""

import pytest
from django.test import override_settings

from server.common.yt_dlp import build_yt_dlp_opts


@pytest.mark.django_db
def test_build_yt_dlp_opts_defaults() -> None:
    """Default opts use the mweb client and no PO token provider."""
    with override_settings(YTDLP_POT_PROVIDER_BASE_URL=''):
        opts = build_yt_dlp_opts(skip_download=True)
    assert opts['skip_download'] is True
    assert opts['extractor_args']['youtube']['player_client'] == ['mweb']
    assert 'youtubepot-bgutilhttp' not in opts['extractor_args']


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
