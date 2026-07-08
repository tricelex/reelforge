"""Tests for the shared Google/YouTube API response classifier."""

from unittest.mock import MagicMock

import pytest

from server.apps.generation.clients._google_api_common import classify_response
from server.common.exceptions import FatalProviderError, RetryableProviderError


def test_classify_response_ok_does_not_raise() -> None:
    resp = MagicMock(status_code=200)
    classify_response(resp, provider='test')


def test_classify_response_retryable_status() -> None:
    resp = MagicMock(status_code=503)
    with pytest.raises(RetryableProviderError):
        classify_response(resp, provider='test')


def test_classify_response_quota_reason_sets_error_code() -> None:
    resp = MagicMock(status_code=403)
    resp.json.return_value = {'error': {'errors': [{'reason': 'quotaExceeded'}]}}
    with pytest.raises(FatalProviderError) as exc_info:
        classify_response(resp, provider='test')
    assert exc_info.value.error_code == 'QUOTA_EXCEEDED'


def test_classify_response_auth_reason_sets_error_code() -> None:
    resp = MagicMock(status_code=403)
    resp.json.return_value = {'error': {'errors': [{'reason': 'forbidden'}]}}
    with pytest.raises(FatalProviderError) as exc_info:
        classify_response(resp, provider='test')
    assert exc_info.value.error_code == 'AUTH_ERROR'


def test_classify_response_malformed_json_still_raises_fatal() -> None:
    resp = MagicMock(status_code=400)
    resp.json.side_effect = ValueError('not json')
    with pytest.raises(FatalProviderError):
        classify_response(resp, provider='test')
