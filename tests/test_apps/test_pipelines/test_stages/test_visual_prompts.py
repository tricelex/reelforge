"""Tests for the visual_prompts stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.visual_prompts import VisualPromptsStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.style_guide = 'cinematic, desaturated'
    ctx.upstream = {
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'beat': 'intro',
                    'narration_text': 'Rome was great.',
                    'visual_concept': 'Aerial view of the Colosseum',
                    'shot_type': 'aerial',
                    'est_seconds': 8.0,
                    'is_hero': True,
                    'foreground_cast': [],
                    'word_count': 15,
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_visual_prompts_stage_key() -> None:
    """VisualPromptsStage has the expected key."""
    assert VisualPromptsStage.key == 'visual_prompts'
    assert VisualPromptsStage.queue == 'api'


def test_visual_prompts_fan_out_none() -> None:
    """visual_prompts is a single-execution stage."""
    assert VisualPromptsStage().fan_out(MagicMock()) is None


def test_visual_prompts_run_returns_prompts() -> None:
    """run() returns dict with 'prompts' list."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    fake_output = VisualPromptsOutput(
        prompts=[
            VisualPrompt(
                scene_idx=0,
                prompt='Aerial view of ancient Colosseum, cinematic, desaturated',
                negative_prompt='modern, cars',
            ),
        ],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'prompts' in result
    assert result['prompts'][0]['scene_idx'] == 0  # type: ignore[index]
    assert 'Colosseum' in result['prompts'][0]['prompt']  # type: ignore[index,operator]
