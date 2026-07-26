"""Internet Archive provider for archival video.

Search results identify archive items; a metadata request then locates the
first playable MP4 file for each item. No API key is required.
"""

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
    except ValueError:
        return 0


def _optional_float(value: object) -> float | None:
    """Convert optional duration metadata, preserving an absent value."""
    if value is None:
        return None
    if isinstance(value, str) and not value:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


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
        """Search archive.org and resolve each item to its first MP4."""
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
        """Fetch item metadata and map its first MP4, if present."""
        identifier = str(doc['identifier'])
        response = await client.get(
            f'{_METADATA_URL}/{quote(identifier, safe="")}',
        )
        self._raise_for_error(response, f'metadata for {identifier}')
        files = response.json().get('files') or []
        mp4_file = self._first_mp4(files)
        if mp4_file is None:
            return None
        return self._candidate(doc, mp4_file)

    def _first_mp4(
        self,
        files: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the first named MP4 within the bounded metadata file list."""
        for file_info in files[:_MAX_FILES_PER_ITEM]:
            name = str(file_info.get('name', ''))
            if name.casefold().endswith('.mp4'):
                return file_info
        return None

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
