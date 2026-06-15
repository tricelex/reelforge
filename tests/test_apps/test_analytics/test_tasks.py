"""Tests for analytics refresh task."""

import asyncio
from unittest.mock import MagicMock, patch

from server.apps.analytics.tasks import refresh_analytics_views


def test_refresh_analytics_views_executes_refresh_sql() -> None:
    """refresh_analytics_views runs REFRESH MATERIALIZED VIEW for all views."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_connection = MagicMock()
    mock_connection.cursor.return_value = mock_cursor

    async def _inner() -> None:
        with patch('django.db.connection', mock_connection):
            await refresh_analytics_views()

    asyncio.run(_inner())

    calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any('analytics_run_cost_summary' in c for c in calls)
    assert any('analytics_channel_roi' in c for c in calls)
    assert any('analytics_stage_performance' in c for c in calls)
