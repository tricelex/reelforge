"""Pexels footage provider — free stock video and photos.

Licence: Pexels licence, attribution not required.
Rate limit: 200 requests/hour on the free tier.

``FootageCandidate`` field paths:

* Video: ``external_id <- videos[].id``;
  ``download_url <- videos[].video_files[].link``;
  ``thumb_url <- videos[].image``; ``source_page_url <- videos[].url``;
  ``width/height <- videos[].video_files[].width/height`` with fallback to
  ``videos[].width/height``; ``duration_s <- videos[].duration``;
  ``author <- videos[].user.name``; ``title <- videos[].alt``.
* Photo: ``external_id <- photos[].id``;
  ``download_url <- photos[].src.original``;
  ``thumb_url <- photos[].src.medium``;
  ``source_page_url <- photos[].url``;
  ``width/height <- photos[].width/height``;
  ``author <- photos[].photographer``; ``title <- photos[].alt``.
* Both: ``provider``, ``media_type``, ``license``, ``license_url``,
  ``attribution_required``, and ``tags`` are adapter constants.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_VIDEO_URL = 'https://api.pexels.com/videos/search'
_PHOTO_URL = 'https://api.pexels.com/v1/search'
_TIMEOUT_S = 20.0


@final
class PexelsProvider:
    """Searches Pexels for stock video and photography."""

    name = 'pexels'

    def __init__(self, api_key: str) -> None:
        """Initialise with the Pexels API key ('' disables the provider)."""
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
        """Search Pexels and return normalised candidates."""
        if not self._api_key:
            return []
        url = _VIDEO_URL if media_type == 'video' else _PHOTO_URL
        params: dict[str, str | int] = {
            'query': query,
            'per_page': limit,
            'orientation': orientation,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                params=params,
                headers={'Authorization': self._api_key},
            )
        if not resp.is_success:
            raise RetryableProviderError(
                f'Pexels {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        data = resp.json()
        if media_type == 'video':
            return [
                self._video_candidate(item, min_width)
                for item in data.get('videos', [])
            ]
        return [self._photo_candidate(item) for item in data.get('photos', [])]

    def _video_candidate(
        self,
        item: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pexels video result, picking the best usable rendition."""
        files = sorted(
            item.get('video_files', []),
            key=lambda f: int(f.get('width') or 0),
            reverse=True,
        )
        usable = [
            file for file in files if int(file.get('width') or 0) >= min_width
        ]
        chosen = (usable[-1] if usable else files[0]) if files else {}
        user = item.get('user') or {}
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='video',
            download_url=str(chosen.get('link', '')),
            thumb_url=str(item.get('image', '')),
            source_page_url=str(item.get('url', '')),
            width=int(chosen.get('width') or item.get('width') or 0),
            height=int(chosen.get('height') or item.get('height') or 0),
            duration_s=float(item.get('duration') or 0.0),
            license='pexels',
            license_url='https://www.pexels.com/license/',
            author=str(user.get('name', '')),
            attribution_required=False,
            title=str(item.get('alt') or ''),
            tags=(),
        )

    def _photo_candidate(self, item: dict[str, Any]) -> FootageCandidate:
        """Map one Pexels photo result."""
        src = item.get('src') or {}
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='image',
            download_url=str(src.get('original', '')),
            thumb_url=str(src.get('medium', '')),
            source_page_url=str(item.get('url', '')),
            width=int(item.get('width') or 0),
            height=int(item.get('height') or 0),
            duration_s=None,
            license='pexels',
            license_url='https://www.pexels.com/license/',
            author=str(item.get('photographer', '')),
            attribution_required=False,
            title=str(item.get('alt') or ''),
            tags=(),
        )
