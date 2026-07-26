"""Tests for profile-based review dispatch."""

from unittest.mock import MagicMock, patch

import pytest

from server.apps.pipelines.review import dispatch


@pytest.mark.django_db
def test_ai_visual_run_uses_the_existing_selector() -> None:
    """Runs with no profile keep today's storyboard payload builder."""
    run = MagicMock()
    run.blueprint_snapshot = {'stages': []}
    presign = MagicMock()

    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.ai_visual.get_storyboard',
            return_value='ai-payload',
        ) as ai_visual,
    ):
        result = dispatch.get_storyboard('run-id', presign)

    assert result == 'ai-payload'
    ai_visual.assert_called_once_with('run-id', presign)


@pytest.mark.django_db
def test_documentary_run_uses_the_footage_selector() -> None:
    """Documentary runs get the footage payload builder."""
    run = MagicMock()
    run.blueprint_snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
    }
    presign = MagicMock()

    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.documentary.get_storyboard',
            return_value='doc-payload',
        ) as doc,
    ):
        result = dispatch.get_storyboard('run-id', presign)

    assert result == 'doc-payload'
    doc.assert_called_once_with('run-id', presign)


@pytest.mark.django_db
def test_scene_edit_stale_key_is_profile_specific() -> None:
    """A documentary scene edit stales footage_queries, not visual_prompts."""
    run = MagicMock()
    run.blueprint_snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
    }
    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.documentary.apply_scene_edit',
            return_value='footage_queries',
        ),
    ):
        assert dispatch.apply_scene_edit('run-id', 0, {}) == 'footage_queries'
