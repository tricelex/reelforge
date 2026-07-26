"""Tests for the AI-visual review adapter."""

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.review import ai_visual


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create an AI-visual review channel with final_gate."""
    return Channel.objects.create(
        name='AI Visual Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
        default_budget_usd='20.00',
    )


@pytest.fixture
def blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create an AI-visual blueprint graph for review stages."""
    return PipelineBlueprint.objects.create(
        name='ai_visual_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'scene_breakdown', 'depends_on': []},
                {'key': 'visual_prompts', 'depends_on': ['scene_breakdown']},
                {'key': 'image_gen', 'depends_on': ['visual_prompts']},
                {'key': 'assembly', 'depends_on': ['image_gen']},
                {
                    'key': 'final_gate',
                    'depends_on': ['assembly'],
                    'gate': True,
                },
                {'key': 'publish', 'depends_on': ['final_gate']},
            ],
        },
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Create an AI-visual run awaiting review."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='AI visual topic',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='2.10',
    )


@pytest.fixture
def scene_breakdown_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded scene_breakdown output with one scene."""
    return StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                {
                    'idx': 0,
                    'narration_text': 'Opening line.',
                    'visual_concept': 'sunrise over hills',
                    'est_seconds': 5.0,
                    'word_count': 2,
                },
            ],
        },
    )


@pytest.fixture
def visual_prompts_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded visual_prompts output for scene 0."""
    return StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'prompts': [
                {
                    'scene_idx': 0,
                    'prompt': 'sunrise concept',
                    'negative_prompt': '',
                },
            ],
        },
    )


@pytest.mark.django_db
def test_get_storyboard_delegates_to_selector(run: PipelineRun) -> None:
    """get_storyboard defers to the shared storyboard selector."""
    presign = MagicMock()
    with patch(
        'server.apps.pipelines.storyboard_selectors.get_storyboard',
        return_value='ai-storyboard-payload',
    ) as selector:
        result = cast(Any, ai_visual.get_storyboard(str(run.id), presign))

    assert result == 'ai-storyboard-payload'
    selector.assert_called_once_with(str(run.id), presign)


@pytest.mark.django_db
def test_apply_scene_edit_updates_breakdown_and_stales_visual_prompts(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
) -> None:
    """A successful edit updates breakdown and syncs visual_prompts."""
    stale_from = ai_visual.apply_scene_edit(
        str(run.id),
        0,
        {
            'narration_text': 'Updated narration line',
            'visual_concept': 'storm clouds gathering',
        },
    )

    assert stale_from == 'visual_prompts'

    scene_breakdown_stage.refresh_from_db()
    scene = scene_breakdown_stage.output['scenes'][0]
    assert scene['narration_text'] == 'Updated narration line'

    visual_prompts_stage.refresh_from_db()
    prompt = visual_prompts_stage.output['prompts'][0]
    assert prompt['prompt'] == 'storm clouds gathering'

    run.refresh_from_db()
    assert run.had_manual_edits is True


@pytest.mark.django_db
def test_apply_scene_edit_without_visual_prompts_stales_scene_breakdown(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
) -> None:
    """Editing when visual_prompts has not succeeded stales scene_breakdown."""
    stale_from = ai_visual.apply_scene_edit(
        str(run.id),
        0,
        {'narration_text': 'No prompts stage yet'},
    )

    assert stale_from == 'scene_breakdown'


@pytest.mark.django_db
def test_apply_scene_edit_missing_breakdown_raises(run: PipelineRun) -> None:
    """A missing scene_breakdown output raises ValidationError."""
    with pytest.raises(ValidationError):
        ai_visual.apply_scene_edit(
            str(run.id),
            0,
            {'narration_text': 'No breakdown yet'},
        )


@pytest.mark.django_db
def test_apply_scene_edit_failed_breakdown_raises(run: PipelineRun) -> None:
    """A failed scene_breakdown execution is treated as unavailable."""
    StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.FAILED,
        attempt=0,
        output={},
    )

    with pytest.raises(ValidationError):
        ai_visual.apply_scene_edit(
            str(run.id),
            0,
            {'narration_text': 'Breakdown failed'},
        )


@pytest.mark.django_db
def test_apply_scene_edit_invalid_breakdown_output_raises(
    run: PipelineRun,
) -> None:
    """A non-list `scenes` field in breakdown output raises ValidationError."""
    StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scenes': 'not-a-list'},
    )

    with pytest.raises(ValidationError):
        ai_visual.apply_scene_edit(
            str(run.id),
            0,
            {'narration_text': 'Bad output'},
        )


@pytest.mark.django_db
def test_apply_scene_edit_scene_not_found_raises(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
) -> None:
    """Editing a scene index absent from breakdown raises ValidationError."""
    with pytest.raises(ValidationError):
        ai_visual.apply_scene_edit(
            str(run.id),
            99,
            {'narration_text': 'Missing scene'},
        )
