"""Pixabay footage provider — free stock video and photos.

Licence: Pixabay content licence, attribution not required.
Rate limit: 100 requests/minute on the free tier.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_VIDEO_URL = 'https://pixabay.com/api/videos/'
_PHOTO_URL = 'https://pixabay.com/api/'
_TIMEOUT_S = 20.0
_LICENSE_URL = 'https://pixabay.com/service/license-summary/'


@final
class PixabayProvider:
    """Searches Pixabay for stock video and photography."""

    name = 'pixabay'

    def __init__(self, api_key: str) -> None:
        """Initialise with the Pixabay API key ('' disables the provider)."""
        self._api_key = api_key

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Pixabay and return normalised candidates."""
        if not self._api_key:
            return []
        url = _VIDEO_URL if media_type == 'video' else _PHOTO_URL
        params: dict[str, Any] = {
            'key': self._api_key,
            'q': query,
            'per_page': max(limit, 3),
        }
        if media_type == 'image':
            params['orientation'] = (
                'horizontal' if orientation == 'landscape' else 'vertical'
            )
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(url, params=params)
        if not resp.is_success:
            raise RetryableProviderError(
                f'Pixabay {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        hits = resp.json().get('hits', [])
        builder = (
            self._video_candidate
            if media_type == 'video'
            else self._photo_candidate
        )
        return [builder(hit, min_width) for hit in hits[:limit]]

    def _video_candidate(
        self,
        hit: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pixabay video hit to the smallest adequate rendition."""
        renditions = [
            rendition
            for rendition in (hit.get('videos') or {}).values()
            if isinstance(rendition, dict) and rendition.get('url')
        ]
        renditions.sort(key=lambda item: int(item.get('width') or 0))
        usable = [
            item
            for item in renditions
            if int(item.get('width') or 0) >= min_width
        ]
        chosen: dict[str, Any] = {}
        if renditions:
            chosen = usable[0] if usable else renditions[-1]
        return FootageCandidate(
            provider=self.name,
            external_id=str(hit.get('id', '')),
            media_type='video',
            download_url=str(chosen.get('url', '')),
            thumb_url=str(hit.get('userImageURL') or ''),
            source_page_url=str(hit.get('pageURL', '')),
            width=int(chosen.get('width') or 0),
            height=int(chosen.get('height') or 0),
            duration_s=float(hit.get('duration') or 0.0),
            license='pixabay',
            license_url=_LICENSE_URL,
            author=str(hit.get('user', '')),
            attribution_required=False,
            title=str(hit.get('tags', '')),
            tags=tuple(
                tag.strip()
                for tag in str(hit.get('tags', '')).split(',')
                if tag.strip()
            ),
        )

    def _photo_candidate(
        self,
        hit: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pixabay photo hit."""
        del min_width  # photos expose a single large rendition
        return FootageCandidate(
            provider=self.name,
            external_id=str(hit.get('id', '')),
            media_type='image',
            download_url=str(hit.get('largeImageURL', '')),
            thumb_url=str(hit.get('previewURL', '')),
            source_page_url=str(hit.get('pageURL', '')),
            width=int(hit.get('imageWidth') or 0),
            height=int(hit.get('imageHeight') or 0),
            duration_s=None,
            license='pixabay',
            license_url=_LICENSE_URL,
            author=str(hit.get('user', '')),
            attribution_required=False,
            title=str(hit.get('tags', '')),
            tags=tuple(
                tag.strip()
                for tag in str(hit.get('tags', '')).split(',')
                if tag.strip()
            ),
        )
