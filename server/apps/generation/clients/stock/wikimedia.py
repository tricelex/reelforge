"""Wikimedia Commons provider — public-domain and CC archival media.

No API key required. Licences and attribution requirements are read from each
file's metadata.
"""

import re
from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_API_URL = 'https://commons.wikimedia.org/w/api.php'
_TIMEOUT_S = 25.0
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(value: str) -> str:
    """Render HTML-bearing Commons metadata as plain text."""
    return _TAG_RE.sub('', value).strip()


@final
class WikimediaProvider:
    """Searches Wikimedia Commons for archival images and video."""

    name = 'wikimedia'

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Commons and return normalised candidates."""
        del orientation, min_width  # Commons has no server-side filters
        filetype = 'video' if media_type == 'video' else 'bitmap'
        params: dict[str, str | int] = {
            'action': 'query',
            'generator': 'search',
            'gsrsearch': f'filetype:{filetype} {query}',
            'gsrlimit': limit,
            'gsrnamespace': 6,
            'prop': 'imageinfo',
            'iiprop': 'url|size|extmetadata',
            'format': 'json',
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(_API_URL, params=params)
        if not resp.is_success:
            raise RetryableProviderError(
                f'Wikimedia {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        pages = (resp.json().get('query') or {}).get('pages') or {}
        return [
            self._candidate(page, media_type)
            for page in pages.values()
            if page.get('imageinfo')
        ]

    def _candidate(
        self,
        page: dict[str, Any],
        media_type: MediaType,
    ) -> FootageCandidate:
        """Map one Commons page with imageinfo to a candidate."""
        info = page['imageinfo'][0]
        meta = info.get('extmetadata') or {}

        def _meta(key: str) -> str:
            entry = meta.get(key) or {}
            return (
                str(entry.get('value', ''))
                if isinstance(entry, dict)
                else ''
            )

        raw_required = _meta('AttributionRequired')
        attribution_required = (
            raw_required.strip().casefold() != 'false' if raw_required else True
        )
        return FootageCandidate(
            provider=self.name,
            external_id=str(page.get('pageid', '')),
            media_type=media_type,
            download_url=str(info.get('url', '')),
            thumb_url=str(info.get('thumburl') or info.get('url', '')),
            source_page_url=str(info.get('descriptionurl', '')),
            width=int(info.get('width') or 0),
            height=int(info.get('height') or 0),
            duration_s=(
                float(info.get('duration') or 0.0)
                if media_type == 'video'
                else None
            ),
            license=_meta('License') or 'unknown',
            license_url='',
            author=_strip_html(_meta('Artist')),
            attribution_required=attribution_required,
            title=str(page.get('title', '')),
            tags=(),
        )
