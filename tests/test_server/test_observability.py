"""Tests for server/common/observability.py."""

from unittest.mock import patch

from server.common.observability import init_logfire, init_sentry


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
    assert kwargs['traces_sample_rate'] == 0.5
    assert kwargs['profiles_sample_rate'] == 0.05
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
    """init_logfire calls configure then all four instrument_* functions."""
    settings.LOGFIRE_TOKEN = 'pylf_v1_test_abc123'
    settings.LOGFIRE_SERVICE_NAME = 'reelforge-test'
    with (
        patch('logfire.configure') as mock_configure,
        patch('logfire.instrument_django') as mock_django,
        patch('logfire.instrument_psycopg') as mock_psycopg2,
        patch('logfire.instrument_redis') as mock_redis,
        patch('logfire.instrument_httpx') as mock_httpx,
    ):
        init_logfire()
    mock_configure.assert_called_once_with(
        token='pylf_v1_test_abc123',
        service_name='reelforge-test',
    )
    mock_django.assert_called_once_with(capture_headers=True)
    mock_psycopg2.assert_called_once_with('psycopg2')
    mock_redis.assert_called_once_with()
    mock_httpx.assert_called_once_with()
