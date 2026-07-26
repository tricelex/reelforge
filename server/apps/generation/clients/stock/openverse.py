"""Openverse provider — CC-licensed and public-domain media.

Media-type support: images only (verified against the live API — see the
project design doc, which originally assumed video support). Video requests
return an empty list so the provider can sit in a channel's priority list
without breaking video-preferring scenes.

Auth: permanent ``client_id`` / ``client_secret`` exchange for a short-lived
Bearer access token (``expires_in`` ≈ 36000s). An optional static ``token``
overrides OAuth for tests. Empty credentials still allow anonymous search.
"""

import time
from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_IMAGE_URL = 'https://api.openverse.org/v1/images/'
_OAUTH_TOKEN_ENDPOINT = 'https://api.openverse.org/v1/auth_tokens/token/'  # noqa: S105
_TIMEOUT_S = 25.0
_TOKEN_SKEW_S = 60.0
_NO_ATTRIBUTION_LICENSES = frozenset({'cc0', 'pdm'})


@final
class OpenverseProvider:
    """Searches Openverse for CC-licensed still imagery."""

    name = 'openverse'

    def __init__(
        self,
        *,
        client_id: str = '',
        client_secret: str = '',
        token: str = '',
    ) -> None:
        """Initialise with OAuth client credentials and/or a Bearer override."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_override = token
        self._cached_token = ''
        self._token_expires_at = 0.0

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
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            bearer = await self._resolve_bearer(client)
            headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}
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

    async def _resolve_bearer(self, client: httpx.AsyncClient) -> str:
        """Return a usable Bearer token, refreshing from client credentials."""
        if self._token_override:
            return self._token_override
        now = time.monotonic()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token
        if not self._client_id or not self._client_secret:
            return ''
        resp = await client.post(
            _OAUTH_TOKEN_ENDPOINT,
            data={
                'grant_type': 'client_credentials',
                'client_id': self._client_id,
                'client_secret': self._client_secret,
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            },
        )
        if not resp.is_success:
            raise RetryableProviderError(
                f'Openverse token {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        payload = resp.json()
        access_token = str(payload.get('access_token', ''))
        expires_in = float(payload.get('expires_in') or 0.0)
        if not access_token or expires_in <= 0:
            raise RetryableProviderError(
                'Openverse token response missing access_token/expires_in',
                provider=self.name,
                status_code=resp.status_code,
            )
        self._cached_token = access_token
        self._token_expires_at = now + max(expires_in - _TOKEN_SKEW_S, 1.0)
        return access_token

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
