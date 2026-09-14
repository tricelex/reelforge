"""Tests for the scene_breakdown stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.schemas import (
    CastMember,
    Scene,
    SceneBreakdownOutput,
)
from server.apps.pipelines.stages.scene_breakdown import SceneBreakdownStage
from server.common.exceptions import FatalProviderError

_TWELVE = 'Rome was great once long ago in the ancient world of days.'


def _scene(
    *,
    idx: int = 0,
    chapter_idx: int = 0,
    narration: str = _TWELVE,
    is_hero: bool = True,
    est_seconds: float = 8.0,
    setting: str = 'Roman forum',
) -> Scene:
    words = len(narration.split())
    return Scene(
        idx=idx,
        chapter_idx=chapter_idx,
        beat='intro',
        narration_text=narration,
        visual_concept='Wide aerial Rome',
        shot_type='aerial',
        est_seconds=est_seconds,
        is_hero=is_hero,
        word_count=words,
        setting=setting,
    )


def _make_ctx(*, chapters: list[dict[str, object]] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.wpm = 158
    if chapters is None:
        chapters = [
            {
                'idx': 0,
                'title': 'Intro',
                'text': _TWELVE,
                'word_count': 12,
                'closing_line': 'Rome fell.',
            },
        ]
    ctx.upstream = {
        'script': {
            'chapters': chapters,
            'total_word_count': sum(
                int(ch.get('word_count', 0)) for ch in chapters
            ),
        },
    }
    ctx.config = {'hero_ratio': 0.15}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_scene_breakdown_stage_key() -> None:
    """SceneBreakdownStage has the expected class attributes."""
    assert SceneBreakdownStage.key == 'scene_breakdown'
    assert SceneBreakdownStage.queue == 'api'


def test_scene_breakdown_fan_out_none() -> None:
    """scene_breakdown is a single-execution stage."""
    assert SceneBreakdownStage().fan_out(MagicMock()) is None


def test_scene_word_count_ok_exempts_stage_direction_scene() -> None:
    """A stage-direction scene bypasses the narration word-count band."""
    from server.apps.pipelines.stages.scene_breakdown import (
        _scene_word_count_ok,
    )

    scene = _scene(narration='[Ambient pause. No narration.]')
    assert _scene_word_count_ok(scene, min_w=20, max_w=40) is True


def test_scene_word_count_ok_enforces_band_for_real_narration() -> None:
    """Real narration still must satisfy the configured word band."""
    from server.apps.pipelines.stages.scene_breakdown import (
        _scene_word_count_ok,
    )

    scene = _scene(narration='Too short for the band.')
    assert _scene_word_count_ok(scene, min_w=20, max_w=40) is False


def test_scene_breakdown_has_output_validator() -> None:
    """The PydanticAI agent has an output validator registered."""
    from server.apps.generation.logic.model_resolver import (
        resolve_model,
        to_pydantic_ai_model,
    )
    from server.apps.pipelines.stages.scene_breakdown import (
        _agent,
    )

    model = to_pydantic_ai_model(resolve_model('scene_breakdown', None))
    assert hasattr(_agent(model), 'output_validator')


def test_scene_breakdown_run_returns_scenes() -> None:
    """run() returns dict with 'scenes' list."""
    ctx = _make_ctx()
    fake_output = SceneBreakdownOutput(scenes=[_scene()])

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
    assert result['scenes'][0]['setting'] == 'Roman forum'  # type: ignore[index]


def test_scene_breakdown_calls_agent_once_per_chapter() -> None:
    """Each script chapter is a separate LLM call, then idxs are stitched."""
    ctx = _make_ctx(
        chapters=[
            {'idx': 0, 'title': 'A', 'text': _TWELVE, 'word_count': 12},
            {'idx': 1, 'title': 'B', 'text': _TWELVE, 'word_count': 12},
        ],
    )
    outputs = [
        SceneBreakdownOutput(scenes=[_scene(chapter_idx=0)]),
        SceneBreakdownOutput(scenes=[_scene(chapter_idx=1, is_hero=False)]),
    ]
    mock_agent = AsyncMock(side_effect=outputs)

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 2
    scenes = result['scenes']
    assert [s['idx'] for s in scenes] == [0, 1]  # type: ignore[index]
    assert [s['chapter_idx'] for s in scenes] == [0, 1]  # type: ignore[index]


def test_scene_breakdown_retries_until_coverage() -> None:
    """Under-covered chapter output is retried before succeeding."""
    ctx = _make_ctx()
    short = _scene(narration='Rome was great once long ago in time.')
    mock_agent = AsyncMock(
        side_effect=[
            SceneBreakdownOutput(scenes=[short]),
            SceneBreakdownOutput(scenes=[_scene()]),
        ],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 2
    assert len(result['scenes']) == 1  # type: ignore[arg-type]


def test_scene_breakdown_raises_when_coverage_never_met() -> None:
    """Exhausted coverage retries become a fatal stage error."""
    ctx = _make_ctx()
    short = _scene(narration='Rome was great once long ago in time.')
    mock_agent = AsyncMock(
        return_value=SceneBreakdownOutput(scenes=[short]),
    )

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            await SceneBreakdownStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.error_code == 'scene_coverage'
    assert mock_agent.await_count == 3


def test_scene_breakdown_clamps_hero_flags() -> None:
    """max_hero_scenes keeps only the first N hero stills."""
    doubled = f'{_TWELVE} {_TWELVE}'
    ctx = _make_ctx(
        chapters=[
            {'idx': 0, 'title': 'Intro', 'text': doubled, 'word_count': 24},
        ],
    )
    ctx.config = {'hero_ratio': 0.15, 'max_hero_scenes': 1}
    fake_output = SceneBreakdownOutput(
        scenes=[
            _scene(idx=0, is_hero=True),
            _scene(idx=1, is_hero=True),
        ],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    flags = [s['is_hero'] for s in result['scenes']]  # type: ignore[index]
    assert flags == [True, False]


def test_scene_breakdown_empty_chapter_with_no_scenes_is_fatal() -> None:
    """A covered empty chapter that yields no scenes still fails."""
    ctx = _make_ctx(
        chapters=[{'idx': 0, 'title': 'A', 'text': '', 'word_count': 0}],
    )
    fake_output = SceneBreakdownOutput(scenes=[])

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            await SceneBreakdownStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.error_code == 'missing_scenes'


def test_scene_breakdown_accepts_stage_direction_only_chapter_without_retry() -> (
    None
):
    """A whole-chapter bracketed stage direction needs no narration coverage."""
    stage_direction = '[Ambient pause. No narration.]'
    ctx = _make_ctx(
        chapters=[
            {'idx': 0, 'title': 'Intro', 'text': _TWELVE, 'word_count': 12},
            {
                'idx': 1,
                'title': 'Breathing Space',
                'text': stage_direction,
                'word_count': len(stage_direction.split()),
            },
        ],
    )
    outputs = [
        SceneBreakdownOutput(scenes=[_scene(chapter_idx=0)]),
        SceneBreakdownOutput(scenes=[]),
    ]
    mock_agent = AsyncMock(side_effect=outputs)

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 2
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
    assert result['scenes'][0]['chapter_idx'] == 0  # type: ignore[index]


def test_scene_breakdown_accepts_low_word_count_stage_direction_scene() -> None:
    """A stage-direction chapter split into one under-band scene still succeeds.

    Reproduces a real failure: the model represented a whole-chapter
    stage direction as a single scene whose narration_text word count
    fell below the configured 20-40 word band, and the output_validator
    rejected it on every attempt until the LLM call itself failed.
    """
    stage_direction = '[Ambient pause. No narration. Water recedes.]'
    ctx = _make_ctx(
        chapters=[
            {
                'idx': 0,
                'title': 'Breathing Space',
                'text': stage_direction,
                'word_count': len(stage_direction.split()),
            },
        ],
    )
    ctx.config = {'hero_ratio': 0.15, 'min_words': 20, 'max_words': 40}
    stage_direction_scene = _scene(
        chapter_idx=0,
        narration=stage_direction,
        is_hero=False,
    )
    mock_agent = AsyncMock(
        return_value=SceneBreakdownOutput(scenes=[stage_direction_scene]),
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 1
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
    assert result['scenes'][0]['word_count'] == 6  # type: ignore[index]


def test_scene_breakdown_missing_chapters_is_fatal() -> None:
    """No script chapters cannot be broken into scenes."""
    ctx = _make_ctx()
    ctx.upstream = {'script': {'chapters': [], 'total_word_count': 0}}

    async def _inner() -> None:
        await SceneBreakdownStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.error_code == 'missing_chapters'


def test_scene_breakdown_unions_cast_across_chapters() -> None:
    """Cast members are merged by name; blanks and duplicates drop."""
    ctx = _make_ctx(
        chapters=[
            {'idx': 0, 'title': 'A', 'text': _TWELVE, 'word_count': 12},
            {'idx': 1, 'title': 'B', 'text': _TWELVE, 'word_count': 12},
        ],
    )
    outputs = [
        SceneBreakdownOutput(
            scenes=[_scene(chapter_idx=0)],
            cast=[
                CastMember(name='Marcus', role='senator', importance='main'),
                CastMember(name='', role='ghost'),
            ],
        ),
        SceneBreakdownOutput(
            scenes=[_scene(chapter_idx=1, is_hero=False)],
            cast=[
                CastMember(name='marcus', role='duplicate'),
                CastMember(name='Livia', role='witness'),
            ],
        ),
    ]

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(side_effect=outputs),
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    names = [row['name'] for row in result['cast']]  # type: ignore[index]
    assert names == ['Marcus', 'Livia']


def test_scene_breakdown_uses_rendered_user_prompt() -> None:
    """A DB template user prompt is preferred over the fallback string."""
    ctx = _make_ctx()
    ctx.prompts.render = AsyncMock(return_value=('sys', 'break this chapter'))
    fake_output = SceneBreakdownOutput(scenes=[_scene()])

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ) as mock_agent:
            result = await SceneBreakdownStage().run(ctx)
            assert mock_agent.await_args.args[1] == 'break this chapter'
            return result

    result = asyncio.run(_inner())
    assert len(result['scenes']) == 1  # type: ignore[arg-type]


def test_scene_breakdown_custom_coverage_limits_accept_short_split() -> None:
    """coverage_ratio_min/max from config override the 95-110% band."""
    ctx = _make_ctx()
    ctx.config = {
        'hero_ratio': 0.15,
        'coverage_ratio_min': 0.5,
        'coverage_ratio_max': 2.0,
    }
    short = _scene(narration='Rome was great once long ago in time.')
    mock_agent = AsyncMock(
        return_value=SceneBreakdownOutput(scenes=[short]),
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await SceneBreakdownStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 1
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
