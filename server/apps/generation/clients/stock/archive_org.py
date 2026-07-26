"""Internet Archive provider for archival video.

Search results identify archive items; a metadata request then locates the
best declared-resolution MP4 file for each item. No API key is required.
"""

import math
import re
from typing import Any, final
from urllib.parse import quote, urlparse

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_SEARCH_URL = 'https://archive.org/advancedsearch.php'
_METADATA_URL = 'https://archive.org/metadata'
_DOWNLOAD_URL = 'https://archive.org/download'
_DETAILS_URL = 'https://archive.org/details'
_THUMB_URL = 'https://archive.org/services/img'
_TIMEOUT_S = 25.0
_MAX_FILES_PER_ITEM = 10_000
_CLOCK_DURATION_RE = re.compile(
    r'^(?:(?P<hours>\d+):)?'
    r'(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)$',
)


def _license_label(license_url: str) -> str:
    """Derive an Openverse-compatible licence label from a CC URL."""
    if not license_url:
        return 'unknown'
    parts = [part.casefold() for part in urlparse(license_url).path.split('/')]
    parts = [part for part in parts if part]
    if len(parts) >= 3 and parts[-3:-1] == ['publicdomain', 'mark']:
        return f'pdm-{parts[-1]}'
    if len(parts) >= 3 and parts[-3:-1] == ['publicdomain', 'zero']:
        return f'cc0-{parts[-1]}'
    if len(parts) >= 3 and parts[-3] == 'licenses':
        return f'{parts[-2]}-{parts[-1]}'
    return license_url


def _attribution_required(license_url: str) -> bool:
    """Return False only for explicit CC0 or Public Domain Mark URLs."""
    label = _license_label(license_url)
    return not label.startswith(('cc0-', 'pdm-'))


def _integer(value: object) -> int:
    """Convert optional archive metadata to an integer safely."""
    if not isinstance(value, (str, int, float)):
        return 0
    try:
        return int(value)
    except (OverflowError, ValueError):
        return 0


def _clock_duration(value: str) -> float | None:
    """Convert an H:MM:SS or M:SS duration to seconds."""
    match = _CLOCK_DURATION_RE.fullmatch(value)
    if match is None:
        return None
    hours_text = match.group('hours')
    hours = int(hours_text or 0)
    minutes = int(match.group('minutes'))
    seconds = float(match.group('seconds'))
    if not math.isfinite(seconds) or seconds >= 60:
        return None
    if hours_text is not None and minutes >= 60:
        return None
    return (hours * 3600) + (minutes * 60) + seconds


def _numeric_duration(value: str | int | float) -> float | None:
    """Convert a scalar duration to finite non-negative seconds."""
    try:
        duration = float(value)
    except ValueError:
        return None
    if not math.isfinite(duration) or duration < 0:
        return None
    return duration


def _optional_float(value: object) -> float | None:
    """Convert optional duration metadata, preserving an absent value."""
    if isinstance(value, str):
        stripped = value.strip()
        return (
            _clock_duration(stripped)
            if ':' in stripped
            else _numeric_duration(stripped)
        )
    if isinstance(value, (int, float)):
        return _numeric_duration(value)
    return None


def _mp4_pixels(file_info: object) -> tuple[dict[str, Any] | None, int]:
    """Return an MP4 metadata row and its declared pixel count."""
    if not isinstance(file_info, dict):
        return None, 0
    name = str(file_info.get('name', ''))
    if not name.casefold().endswith('.mp4'):
        return None, 0
    width = _integer(file_info.get('width'))
    height = _integer(file_info.get('height'))
    pixels = width * height if width > 0 and height > 0 else 0
    return file_info, pixels


@final
class ArchiveOrgProvider:
    """Searches the Internet Archive for playable archival video."""

    name = 'archive_org'

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search archive.org and resolve each item to its best MP4."""
        del orientation, min_width
        if media_type != 'video':
            return []
        params: dict[str, Any] = {
            'q': f'{query} AND mediatype:movies',
            'fl[]': ['identifier', 'title', 'licenseurl'],
            'rows': limit,
            'output': 'json',
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(_SEARCH_URL, params=params)
            self._raise_for_error(response, 'search')
            docs = (response.json().get('response') or {}).get('docs') or []
            candidates = []
            for doc in docs[:limit]:
                candidate = await self._resolve_candidate(client, doc)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    async def _resolve_candidate(
        self,
        client: httpx.AsyncClient,
        doc: dict[str, Any],
    ) -> FootageCandidate | None:
        """Fetch item metadata and map its best MP4, if present."""
        identifier = str(doc['identifier'])
        response = await client.get(
            f'{_METADATA_URL}/{quote(identifier, safe="")}',
        )
        self._raise_for_error(response, f'metadata for {identifier}')
        metadata = response.json()
        files = metadata.get('files') if isinstance(metadata, dict) else None
        mp4_file = self._best_mp4(files)
        if mp4_file is None:
            return None
        return self._candidate(doc, mp4_file)

    def _best_mp4(
        self,
        files: object,
    ) -> dict[str, Any] | None:
        """Return the highest-resolution MP4 with declared dimensions."""
        if not isinstance(files, list):
            return None
        fallback: dict[str, Any] | None = None
        best: dict[str, Any] | None = None
        best_pixels = 0
        for file_info in files[:_MAX_FILES_PER_ITEM]:
            mp4_file, pixels = _mp4_pixels(file_info)
            if mp4_file is None:
                continue
            fallback = fallback or mp4_file
            if pixels > best_pixels:
                best = mp4_file
                best_pixels = pixels
        return best or fallback

    def _candidate(
        self,
        doc: dict[str, Any],
        file_info: dict[str, Any],
    ) -> FootageCandidate:
        """Map one archive search document and MP4 file."""
        identifier = str(doc['identifier'])
        file_name = str(file_info['name'])
        license_url = str(doc.get('licenseurl') or '')
        encoded_identifier = quote(identifier, safe='')
        return FootageCandidate(
            provider=self.name,
            external_id=identifier,
            media_type='video',
            download_url=(
                f'{_DOWNLOAD_URL}/{encoded_identifier}/'
                f'{quote(file_name, safe="")}'
            ),
            thumb_url=f'{_THUMB_URL}/{encoded_identifier}',
            source_page_url=f'{_DETAILS_URL}/{encoded_identifier}',
            width=_integer(file_info.get('width')),
            height=_integer(file_info.get('height')),
            duration_s=_optional_float(file_info.get('length')),
            license=_license_label(license_url),
            license_url=license_url,
            author=str(doc.get('creator') or ''),
            attribution_required=_attribution_required(license_url),
            title=str(doc.get('title') or ''),
            tags=(),
        )

    def _raise_for_error(
        self,
        response: httpx.Response,
        operation: str,
    ) -> None:
        """Raise a retryable provider error for an unsuccessful HTTP call."""
        if response.is_success:
            return
        raise RetryableProviderError(
            f'archive.org {operation} {response.status_code}: '
            f'{response.text[:200]}',
            provider=self.name,
            status_code=response.status_code,
        )
