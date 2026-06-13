"""Tests for server/apps/core/apps.py."""

from unittest.mock import patch

from django.apps import apps


def test_core_config_ready_calls_init_sentry_and_init_logfire() -> None:
    """CoreConfig.ready() initialises Sentry and Logfire in order."""
    with (
        patch('server.apps.core.apps.init_sentry') as mock_sentry,
        patch('server.apps.core.apps.init_logfire') as mock_logfire,
    ):
        apps.get_app_config('core').ready()
    mock_sentry.assert_called_once_with()
    mock_logfire.assert_called_once_with()
