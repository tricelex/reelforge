"""Tests for profile-based review dispatch."""

from unittest.mock import MagicMock, patch

import pytest

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)
from server.apps.pipelines.review import dispatch


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a review channel for exercising the real `_load_run` path."""
    return Channel.objects.create(
        name='Dispatch Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
        default_budget_usd='10.00',
    )


@pytest.fixture
def blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create a default (ai_visual) blueprint graph."""
    return PipelineBlueprint.objects.create(
        name='dispatch_ai_visual_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Create a run persisted to the database (no `_load_run` mocking)."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Dispatch topic',
        status=RunStatus.AWAITING_REVIEW,
    )


@pytest.mark.django_db
def test_load_run_real_path_resolves_ai_visual_adapter(
    run: PipelineRun,
) -> None:
    """`_load_run` fetches the run from the database by UUID."""
    presign = MagicMock()

    with patch(
        'server.apps.pipelines.review.ai_visual.get_storyboard',
        return_value='ai-payload',
    ) as ai_visual_get:
        result = dispatch.get_storyboard(str(run.id), presign)

    assert result == 'ai-payload'
    ai_visual_get.assert_called_once_with(str(run.id), presign)


@pytest.mark.django_db
def test_load_run_real_path_resolves_documentary_adapter(
    channel: Channel,
) -> None:
    """`_load_run` resolves documentary profiles from the real run row."""
    blueprint = PipelineBlueprint.objects.create(
        name='dispatch_documentary_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [], 'profile': 'documentary_footage'},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Dispatch documentary topic',
        status=RunStatus.AWAITING_REVIEW,
    )

    with patch(
        'server.apps.pipelines.review.documentary.apply_scene_edit',
        return_value='footage_queries',
    ) as doc_apply:
        result = dispatch.apply_scene_edit(str(run.id), 0, {})

    assert result == 'footage_queries'
    doc_apply.assert_called_once_with(str(run.id), 0, {})


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
