"""Tests for the scene_breakdown stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.scene_breakdown import SceneBreakdownStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.wpm = 158
    ctx.upstream = {
        'script': {
            'chapters': [
                {
                    'idx': 0,
                    'title': 'Intro',
                    'text': 'This is about Rome. ' * 5,
                    'word_count': 20,
                    'closing_line': 'Rome fell.',
                },
            ],
            'total_word_count': 20,
        },
    }
    ctx.config = {'hero_ratio': 0.15}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_scene_breakdown_stage_key() -> None:
    """SceneBreakdownStage has the expected class attributes."""
    assert SceneBreakdownStage.key == 'scene_breakdown'
    assert SceneBreakdownStage.queue == 'api'


def test_scene_breakdown_fan_out_none() -> None:
    """scene_breakdown is a single-execution stage."""
    assert SceneBreakdownStage().fan_out(MagicMock()) is None


def test_scene_breakdown_has_output_validator() -> None:
    """The PydanticAI agent has an output validator registered."""
    from server.apps.pipelines.stages.scene_breakdown import (
        _agent,
    )

    assert hasattr(_agent(), 'output_validator')


def test_scene_breakdown_run_returns_scenes() -> None:
    """run() returns dict with 'scenes' list."""
    from server.apps.pipelines.schemas import (  # noqa: PLC0415
        Scene,
        SceneBreakdownOutput,
    )

    ctx = _make_ctx()
    scenes = [
        Scene(
            idx=0,
            chapter_idx=0,
            beat='intro',
            narration_text='Rome was great once, long ago.',
            visual_concept='Wide aerial Rome',
            shot_type='aerial',
            est_seconds=8.0,
            is_hero=True,
            word_count=20,
        ),
    ]
    fake_output = SceneBreakdownOutput(scenes=scenes)

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'scenes' in result
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
    assert result['scenes'][0]['is_hero'] is True  # type: ignore[index]
