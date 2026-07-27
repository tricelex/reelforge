"""Tests for clip background tasks."""

import asyncio
from unittest.mock import patch

import pytest

from server.apps.clips.tasks import (
    render_clip_export_task,
    render_clip_preview_task,
)


@pytest.mark.django_db
def test_render_clip_preview_task_delegates() -> None:
    """render_clip_preview_task wraps the sync preview helper."""
    with patch(
        'server.apps.clips.tasks_render.render_clip_preview_sync',
    ) as mock_render:
        asyncio.run(render_clip_preview_task('candidate-id'))
    mock_render.assert_called_once_with('candidate-id')


@pytest.mark.django_db
def test_render_clip_export_task_delegates() -> None:
    """render_clip_export_task wraps the sync export helper."""
    with patch(
        'server.apps.clips.tasks_render.render_clip_export_sync',
    ) as mock_render:
        asyncio.run(render_clip_export_task('candidate-id'))
    mock_render.assert_called_once_with('candidate-id')
