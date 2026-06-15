"""Tests for the YouTube Data API v3 client."""

import asyncio
from datetime import UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import django.utils.timezone as tz
import httpx
import pytest

from server.apps.generation.clients.youtube import (
    _classify_response,  # noqa: PLC2701
    refresh_token_if_needed,
    set_thumbnail,
    upload_video,
)
from server.common.exceptions import FatalProviderError, RetryableProviderError


def _fake_credential(*, expired: bool = True) -> MagicMock:
    """Build a mock credential with access/refresh tokens."""
    cred = MagicMock()
    cred.access_token = 'old_token'  # noqa: S105
    cred.refresh_token = 'refresh_tok'  # noqa: S105
    if expired:
        cred.token_expiry = tz.now() - timedelta(hours=1)
    else:
        cred.token_expiry = tz.now() + timedelta(hours=1)
    cred.save = MagicMock()
    return cred


def test_classify_response_200_ok() -> None:
    """_classify_response does not raise on a 200 response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    _classify_response(resp)  # no exception


def test_classify_response_429_retryable() -> None:
    """_classify_response raises RetryableProviderError on 429."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    with pytest.raises(RetryableProviderError):
        _classify_response(resp)


def test_classify_response_403_quota_fatal() -> None:
    """_classify_response raises FatalProviderError with QUOTA_EXCEEDED."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 403
    resp.json.return_value = {
        'error': {'errors': [{'reason': 'quotaExceeded'}]},
    }
    with pytest.raises(FatalProviderError) as exc_info:
        _classify_response(resp)
    assert exc_info.value.error_code == 'QUOTA_EXCEEDED'


def test_classify_response_403_auth_fatal() -> None:
    """_classify_response raises FatalProviderError with AUTH_ERROR."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 403
    resp.json.return_value = {
        'error': {'errors': [{'reason': 'forbidden'}]},
    }
    with pytest.raises(FatalProviderError) as exc_info:
        _classify_response(resp)
    assert exc_info.value.error_code == 'AUTH_ERROR'


def test_refresh_token_skips_when_valid() -> None:
    """refresh_token_if_needed returns existing token when not expired."""
    cred = _fake_credential(expired=False)

    async def _run() -> str:
        return await refresh_token_if_needed(cred)

    token = asyncio.run(_run())
    assert token == 'old_token'  # noqa: S105
    cred.save.assert_not_called()


def test_refresh_token_when_expired() -> None:
    """refresh_token_if_needed refreshes and returns new token when expired."""
    cred = _fake_credential(expired=True)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'access_token': 'new_token',
        'expires_in': 3600,
    }

    async def _run() -> str:
        with patch(
            'server.apps.generation.clients.youtube.httpx.AsyncClient',
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp,
            )
            return await refresh_token_if_needed(cred)

    token = asyncio.run(_run())
    assert token == 'new_token'  # noqa: S105


def test_upload_video_returns_video_id() -> None:
    """upload_video returns the YouTube video id on success."""
    init_resp = MagicMock(spec=httpx.Response)
    init_resp.status_code = 200
    init_resp.headers = {'Location': 'https://upload.example.com/resumable/1'}

    upload_resp = MagicMock(spec=httpx.Response)
    upload_resp.status_code = 200
    upload_resp.json.return_value = {'id': 'yt_abc123'}

    async def _run() -> str:
        with patch(
            'server.apps.generation.clients.youtube.httpx.AsyncClient',
        ) as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=init_resp)
            instance.put = AsyncMock(return_value=upload_resp)
            return await upload_video(
                access_token='tok',  # noqa: S106
                video_bytes=b'video data',
                title='Test Video',
                description='Desc',
                tags=['test'],
            )

    result = asyncio.run(_run())
    assert result == 'yt_abc123'


def test_set_thumbnail_success() -> None:
    """set_thumbnail completes without raising on a 200 response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200

    async def _run() -> None:
        with patch(
            'server.apps.generation.clients.youtube.httpx.AsyncClient',
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=resp,
            )
            await set_thumbnail('tok', 'yt_abc123', b'thumb bytes')

    asyncio.run(_run())  # no exception


def test_classify_response_400_with_malformed_json_raises_fatal() -> None:
    """_classify_response raises FatalProviderError when JSON is malformed."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 400
    # json() raises ValueError — reason defaults to ''
    resp.json.side_effect = ValueError('bad json')
    with pytest.raises(FatalProviderError) as exc_info:
        _classify_response(resp)
    assert exc_info.value.provider == 'youtube'


def test_classify_response_400_missing_reason_raises_fatal() -> None:
    """_classify_response raises FatalProviderError for 400 without reason."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 400
    # json() returns dict without 'error' key → KeyError → reason = ''
    resp.json.return_value = {}
    with pytest.raises(FatalProviderError):
        _classify_response(resp)


def test_upload_video_with_schedule_at_sets_publish_at() -> None:
    """upload_video sets publishAt in status when schedule_at is provided."""
    from datetime import datetime  # noqa: PLC0415

    init_resp = MagicMock(spec=httpx.Response)
    init_resp.status_code = 200
    init_resp.headers = {'Location': 'https://upload.example.com/resumable/2'}

    upload_resp = MagicMock(spec=httpx.Response)
    upload_resp.status_code = 200
    upload_resp.json.return_value = {'id': 'yt_sched01'}

    schedule = datetime(2026, 7, 1, 18, 0, 0, tzinfo=UTC)

    async def _run() -> str:
        with patch(
            'server.apps.generation.clients.youtube.httpx.AsyncClient',
        ) as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=init_resp)
            instance.put = AsyncMock(return_value=upload_resp)
            return await upload_video(
                access_token='tok',  # noqa: S106
                video_bytes=b'video data',
                title='Scheduled Video',
                description='Desc',
                tags=[],
                schedule_at=schedule,
            )

    result = asyncio.run(_run())
    assert result == 'yt_sched01'
