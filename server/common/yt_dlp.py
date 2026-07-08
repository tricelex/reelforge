"""Shared yt-dlp option helpers."""

from typing import Any

from django.conf import settings


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
        'extractor_args': extractor_args,
    }
    opts.update(overrides)
    return opts
