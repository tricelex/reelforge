"""Shared response-classification for Google/YouTube API clients.

The Data API v3, YouTube Analytics API, and YouTube search endpoints all
return errors in the same googleapis error envelope and share the same
retryable-status-code set. Centralizing this means the quota/auth-reason
distinction (used to raise a more specific FatalProviderError.error_code)
is defined once instead of drifting across clients that redefine their own
stripped-down copy.
"""

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

RETRYABLE_CODES = {429, 500, 502, 503, 504}
QUOTA_REASONS = {'quotaExceeded', 'dailyLimitExceeded'}
AUTH_REASONS = {'authError', 'forbidden', 'insufficientPermissions'}


def classify_response(resp: httpx.Response, provider: str) -> None:
    """Raise the appropriate provider error for a non-2xx response."""
    if resp.status_code in {200, 201}:
        return
    if resp.status_code in RETRYABLE_CODES:
        raise RetryableProviderError(
            f'{provider} API {resp.status_code}',
            provider=provider,
            status_code=resp.status_code,
        )
    try:
        reason: str = resp.json()['error']['errors'][0]['reason']
    except (KeyError, IndexError, ValueError, TypeError):
        reason = ''
    if reason in QUOTA_REASONS:
        raise FatalProviderError(
            f'{provider} quota exceeded: {reason}',
            provider=provider,
            error_code='QUOTA_EXCEEDED',
        )
    if reason in AUTH_REASONS:
        raise FatalProviderError(
            f'{provider} auth error: {reason}',
            provider=provider,
            error_code='AUTH_ERROR',
        )
    raise FatalProviderError(
        f'{provider} API error {resp.status_code}: {reason}',
        provider=provider,
    )
