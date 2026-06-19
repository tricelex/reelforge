"""YouTube Data API v3 client — upload video and set thumbnail."""

from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

import django.utils.timezone as tz
import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_QUOTA_REASONS = {'quotaExceeded', 'dailyLimitExceeded'}
_AUTH_REASONS = {'authError', 'forbidden', 'insufficientPermissions'}

_OAUTH_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # noqa: S105
_UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'
_THUMBNAIL_URL = 'https://www.googleapis.com/upload/youtube/v3/thumbnails/set'


@runtime_checkable
class _OAuthCredential(Protocol):
    """Minimal interface expected of a YouTube OAuth credential object."""

    access_token: str
    refresh_token: str
    token_expiry: Any

    def save(self, *, update_fields: list[str]) -> None: ...


def _classify_response(resp: httpx.Response) -> None:
    """Raise the appropriate error for non-2xx responses."""
    if resp.status_code in {200, 201}:
        return
    if resp.status_code in _RETRYABLE_CODES:
        raise RetryableProviderError(
            f'YouTube API {resp.status_code}',
            provider='youtube',
            status_code=resp.status_code,
        )
    try:
        reason: str = resp.json()['error']['errors'][0]['reason']
    except (KeyError, IndexError, ValueError):
        reason = ''
    if reason in _QUOTA_REASONS:
        raise FatalProviderError(
            f'YouTube quota exceeded: {reason}',
            provider='youtube',
            error_code='QUOTA_EXCEEDED',
        )
    if reason in _AUTH_REASONS:
        raise FatalProviderError(
            f'YouTube auth error: {reason}',
            provider='youtube',
            error_code='AUTH_ERROR',
        )
    raise FatalProviderError(
        f'YouTube API error {resp.status_code}: {reason}',
        provider='youtube',
    )


def _save_token_sync(
    credential: _OAuthCredential,
    access_token: str,
    expires_in: int,
) -> None:
    """Persist refreshed OAuth token to the credential model (sync)."""
    credential.access_token = access_token
    credential.token_expiry = tz.now() + timedelta(seconds=expires_in - 60)
    credential.save(update_fields=['access_token', 'token_expiry'])


async def refresh_token_if_needed(credential: _OAuthCredential) -> str:
    """Return a valid access token, refreshing via OAuth if expired."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415
    from django.conf import settings  # noqa: PLC0415

    now = tz.now()
    if credential.token_expiry and credential.token_expiry > now:
        return credential.access_token

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _OAUTH_TOKEN_URL,
            data={
                'client_id': settings.YOUTUBE_CLIENT_ID,
                'client_secret': settings.YOUTUBE_CLIENT_SECRET,
                'refresh_token': credential.refresh_token,
                'grant_type': 'refresh_token',
            },
        )
    _classify_response(resp)
    data: dict[str, Any] = resp.json()
    access_token = str(data['access_token'])
    expires_in = int(data.get('expires_in', 3600))
    await sync_to_async(_save_token_sync)(credential, access_token, expires_in)
    return access_token


class _Schedulable(Protocol):
    """Object with an isoformat() method (e.g. datetime)."""

    def isoformat(self) -> str: ...


async def upload_video(
    access_token: str,
    video_bytes: bytes,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = '27',
    schedule_at: _Schedulable | None = None,
    made_for_kids: bool = False,  # noqa: FBT001, FBT002
) -> str:
    """Resumable upload to YouTube. Returns the youtube_video_id."""
    status: dict[str, object] = {
        'privacyStatus': 'private' if schedule_at else 'public',
        'selfDeclaredMadeForKids': made_for_kids,
    }
    if schedule_at is not None:
        status['publishAt'] = schedule_at.isoformat()

    body: dict[str, object] = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': category_id,
        },
        'status': status,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        init_resp = await client.post(
            _UPLOAD_URL,
            params={'uploadType': 'resumable', 'part': 'snippet,status'},
            headers={
                'Authorization': f'Bearer {access_token}',
                'X-Upload-Content-Type': 'video/*',
                'X-Upload-Content-Length': str(len(video_bytes)),
                'Content-Type': 'application/json',
            },
            json=body,
        )
    _classify_response(init_resp)
    upload_uri: str = init_resp.headers['Location']

    async with httpx.AsyncClient(timeout=1800) as client:
        upload_resp = await client.put(
            upload_uri,
            content=video_bytes,
            headers={'Content-Type': 'video/*'},
        )
    _classify_response(upload_resp)
    return str(upload_resp.json()['id'])


async def set_thumbnail(
    access_token: str,
    video_id: str,
    thumbnail_bytes: bytes,
) -> None:
    """Upload a thumbnail image for an existing YouTube video."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _THUMBNAIL_URL,
            params={'videoId': video_id},
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'image/jpeg',
            },
            content=thumbnail_bytes,
        )
    _classify_response(resp)
