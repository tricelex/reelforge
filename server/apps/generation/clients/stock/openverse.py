"""Openverse provider — CC-licensed and public-domain media.

Media-type support: images only (verified against the live API — see the
project design doc, which originally assumed video support). Video requests
return an empty list so the provider can sit in a channel's priority list
without breaking video-preferring scenes.

An API token raises rate limits but is not required.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_IMAGE_URL = 'https://api.openverse.org/v1/images/'
_TIMEOUT_S = 25.0
_NO_ATTRIBUTION_LICENSES = frozenset({'cc0', 'pdm'})


@final
class OpenverseProvider:
    """Searches Openverse for CC-licensed still imagery."""

    name = 'openverse'

    def __init__(self, token: str = '') -> None:
        """Initialise with an optional Openverse API token."""
        self._token = token

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Openverse images; video is unsupported and returns []."""
        del orientation, min_width
        if media_type != 'image':
            return []
        headers = (
            {'Authorization': f'Bearer {self._token}'} if self._token else {}
        )
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                _IMAGE_URL,
                params={'q': query, 'page_size': limit},
                headers=headers,
            )
        if not resp.is_success:
            raise RetryableProviderError(
                f'Openverse {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        return [
            self._candidate(item) for item in resp.json().get('results', [])
        ]

    def _candidate(self, item: dict[str, Any]) -> FootageCandidate:
        """Map one Openverse result to a candidate."""
        license_code = str(item.get('license', '')).lower()
        version = str(item.get('license_version', ''))
        label = f'{license_code}-{version}'.strip('-') or 'unknown'
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='image',
            download_url=str(item.get('url', '')),
            thumb_url=str(item.get('thumbnail') or item.get('url', '')),
            source_page_url=str(item.get('foreign_landing_url', '')),
            width=int(item.get('width') or 0),
            height=int(item.get('height') or 0),
            duration_s=None,
            license=label,
            license_url=str(item.get('license_url', '')),
            author=str(item.get('creator', '')),
            attribution_required=(license_code not in _NO_ATTRIBUTION_LICENSES),
            title=str(item.get('title', '')),
            tags=(),
        )
