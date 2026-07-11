"""Tests for server/common/observability.py."""

import re
from unittest.mock import patch

import logfire
import pytest

from server.common.observability import (
    init_logfire,
    init_sentry,
    scrubbing_callback,
)


def _scrub_match(
    *,
    path: tuple[str, ...],
    value: str,
    matched: str,
) -> logfire.ScrubMatch:
    return logfire.ScrubMatch(
        path=path,
        value=value,
        pattern_match=re.search(matched, matched, re.IGNORECASE),
    )


@pytest.mark.parametrize(
    ('matched', 'value'),
    [
        ('cookie', 'missing cookie header'),
        ('Cookie', 'missing Cookie header'),
        ('apikey', 'invalid apikey format'),
        ('api_key', 'missing api_key in config'),
        ('api-key', 'api-key not found'),
        ('api key', 'api key required'),
    ],
)
def test_scrubbing_callback_preserves_benign_error_messages(
    matched: str,
    value: str,
) -> None:
    """Error messages mentioning cookie/api-key wording are not redacted."""
    match = _scrub_match(
        path=('attributes', 'error', 'message'),
        value=value,
        matched=matched,
    )
    assert scrubbing_callback(match) == value


@pytest.mark.parametrize(
    ('path', 'matched'),
    [
        (('attributes', 'error', 'message'), 'password'),
        (('attributes', 'other', 'message'), 'cookie'),
    ],
)
def test_scrubbing_callback_redacts_other_matches(
    path: tuple[str, ...],
    matched: str,
) -> None:
    """Only error.message cookie/api-key wording is exempt from scrubbing."""
    match = _scrub_match(path=path, value='some value', matched=matched)
    assert scrubbing_callback(match) is None


def test_init_sentry_is_noop_without_dsn(settings) -> None:
    """init_sentry does nothing when SENTRY_DSN is empty."""
    settings.SENTRY_DSN = ''
    with patch('sentry_sdk.init') as mock_init:
        init_sentry()
    mock_init.assert_not_called()


def test_init_sentry_calls_sdk_init_with_correct_config(settings) -> None:
    """init_sentry passes DSN, env, sample rates, and correct integrations."""
    settings.SENTRY_DSN = 'https://key@o123.ingest.sentry.io/456'
    settings.DJANGO_ENV = 'test'
    settings.SENTRY_TRACES_SAMPLE_RATE = 0.5
    settings.SENTRY_PROFILES_SAMPLE_RATE = 0.05
    with patch('sentry_sdk.init') as mock_init:
        init_sentry()
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs['dsn'] == 'https://key@o123.ingest.sentry.io/456'
    assert kwargs['environment'] == 'test'
    assert kwargs['traces_sample_rate'] == pytest.approx(0.5)
    assert kwargs['profiles_sample_rate'] == pytest.approx(0.05)
    assert kwargs['send_default_pii'] is False


def test_init_logfire_is_noop_without_token(settings) -> None:
    """init_logfire does nothing when LOGFIRE_TOKEN is empty."""
    settings.LOGFIRE_TOKEN = ''
    with patch('logfire.configure') as mock_configure:
        init_logfire()
    mock_configure.assert_not_called()


def test_init_logfire_configures_and_instruments_all_integrations(
    settings,
) -> None:
    """init_logfire calls configure then all instrument_* functions."""
    settings.LOGFIRE_TOKEN = 'test-logfire-token'
    settings.LOGFIRE_SERVICE_NAME = 'reelforge-test'
    with (
        patch('logfire.configure') as mock_configure,
        patch('logfire.instrument_django') as mock_django,
        patch('logfire.instrument_httpx') as mock_httpx,
        patch('logfire.instrument_pydantic_ai') as mock_pydantic_ai,
        patch('logfire.instrument_requests') as mock_requests,
        patch('logfire.LogfireLoggingHandler') as mock_handler,
        patch('logging.getLogger') as mock_get_logger,
    ):
        mock_get_logger.return_value.handlers = []
        init_logfire()
    mock_configure.assert_called_once_with(
        token='test-logfire-token',
        service_name='reelforge-test',
        scrubbing=logfire.ScrubbingOptions(callback=scrubbing_callback),
    )
    mock_django.assert_called_once_with(
        capture_headers=False,
        excluded_urls='/health/',
    )
    mock_httpx.assert_called_once_with()
    mock_pydantic_ai.assert_called_once_with()
    mock_requests.assert_called_once_with()
    mock_handler.assert_called_once_with()
    mock_get_logger.assert_called_once_with()
    mock_get_logger.return_value.addHandler.assert_called_once_with(
        mock_handler.return_value,
    )


def test_init_logfire_skips_handler_when_already_present(settings) -> None:
    """init_logfire does not add a second LogfireLoggingHandler if one exists."""
    import logfire

    settings.LOGFIRE_TOKEN = 'test-logfire-token'
    settings.LOGFIRE_SERVICE_NAME = 'reelforge-test'
    existing_handler = logfire.LogfireLoggingHandler()
    with (
        patch('logfire.configure'),
        patch('logfire.instrument_django'),
        patch('logfire.instrument_httpx'),
        patch('logfire.instrument_pydantic_ai'),
        patch('logfire.instrument_requests'),
        patch('logging.getLogger') as mock_get_logger,
    ):
        mock_get_logger.return_value.handlers = [existing_handler]
        init_logfire()
    mock_get_logger.return_value.addHandler.assert_not_called()
