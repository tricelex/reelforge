"""Tests for the visual_prompts stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.visual_prompts import VisualPromptsStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.lore_document = 'cinematic, desaturated'
    ctx.channel.niche_config.angle = 'fall of empires'
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
                    'setting': 'Colosseum ruins',
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
    assert 'cinematic, desaturated' in result['prompts'][0]['prompt']  # type: ignore[index,operator]
    assert 'Colosseum ruins' in result['prompts'][0]['prompt']  # type: ignore[index,operator]
    assert 'appearance drift' in result['prompts'][0]['negative_prompt']  # type: ignore[index,operator]


def test_visual_prompts_batches_by_chapter() -> None:
    """One LLM call per chapter, then prompts are concatenated."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    ctx.upstream['scene_breakdown']['scenes'] = [
        {
            'idx': 0,
            'chapter_idx': 0,
            'setting': 'forum',
            'foreground_cast': [],
        },
        {
            'idx': 1,
            'chapter_idx': 0,
            'setting': 'forum interior',
            'foreground_cast': [],
        },
        {
            'idx': 2,
            'chapter_idx': 1,
            'setting': 'harbor',
            'foreground_cast': [],
        },
    ]
    mock_agent = AsyncMock(
        side_effect=[
            VisualPromptsOutput(
                prompts=[
                    VisualPrompt(scene_idx=0, prompt='forum shot'),
                    VisualPrompt(scene_idx=1, prompt='interior shot'),
                ],
            ),
            VisualPromptsOutput(
                prompts=[VisualPrompt(scene_idx=2, prompt='harbor shot')],
            ),
        ],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=mock_agent,
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    assert mock_agent.await_count == 2
    assert [p['scene_idx'] for p in result['prompts']] == [0, 1, 2]  # type: ignore[index]


def test_visual_prompts_missing_scenes_is_fatal() -> None:
    """No scene_breakdown scenes cannot produce prompts."""
    from server.common.exceptions import FatalProviderError

    ctx = _make_ctx()
    ctx.upstream = {'scene_breakdown': {'scenes': []}}

    async def _inner() -> None:
        await VisualPromptsStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.error_code == 'missing_scenes'


def test_visual_prompts_coverage_mismatch_is_fatal() -> None:
    """LLM output that skips a scene idx fails closed."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )
    from server.common.exceptions import FatalProviderError

    ctx = _make_ctx()
    fake_output = VisualPromptsOutput(
        prompts=[VisualPrompt(scene_idx=99, prompt='wrong')],
    )

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            await VisualPromptsStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.error_code == 'prompt_coverage'


def test_visual_prompts_uses_rendered_user_prompt() -> None:
    """A DB template user prompt is preferred over the fallback string."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    ctx.prompts.render = AsyncMock(return_value=('sys', 'write these prompts'))
    fake_output = VisualPromptsOutput(
        prompts=[VisualPrompt(scene_idx=0, prompt='aerial colosseum')],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ) as mock_agent:
            result = await VisualPromptsStage().run(ctx)
            assert mock_agent.await_args.args[1] == 'write these prompts'
            return result

    result = asyncio.run(_inner())
    assert result['prompts'][0]['scene_idx'] == 0  # type: ignore[index]


def test_visual_prompts_attaches_appearance_and_character_ref() -> None:
    """Approved hero refs and appearance text lock onto matching scenes."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    ctx.upstream['scene_breakdown']['scenes'][0]['foreground_cast'] = [
        'Unknown',
        'Marcus',
    ]
    fake_output = VisualPromptsOutput(
        prompts=[VisualPrompt(scene_idx=0, prompt='forum two-shot')],
    )
    locks = {
        'marcus': {
            'appearance_prompt': 'grey beard, crimson toga',
            'character_ref_id': 'hero-ref-id',
        },
    }

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.visual_prompts._cast_locks',
                new=AsyncMock(return_value=locks),
            ),
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    prompt = result['prompts'][0]  # type: ignore[index]
    assert 'grey beard, crimson toga' in prompt['prompt']
    assert prompt['character_ref_id'] == 'hero-ref-id'


def test_visual_prompts_keeps_llm_character_ref() -> None:
    """An LLM-supplied character_ref_id is not overwritten."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    ctx.upstream['scene_breakdown']['scenes'][0]['foreground_cast'] = [
        'Marcus',
    ]
    fake_output = VisualPromptsOutput(
        prompts=[
            VisualPrompt(
                scene_idx=0,
                prompt='forum two-shot',
                character_ref_id='already-set',
            ),
        ],
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.visual_prompts._cast_locks',
                new=AsyncMock(
                    return_value={
                        'marcus': {
                            'appearance_prompt': '',
                            'character_ref_id': 'should-not-win',
                        },
                    },
                ),
            ),
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['prompts'][0]['character_ref_id'] == 'already-set'  # type: ignore[index]


def test_visual_prompts_missing_niche_skips_lore() -> None:
    """A channel without NicheConfig still produces prompts."""
    from django.core.exceptions import ObjectDoesNotExist

    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()

    class _NoNiche(MagicMock):
        @property
        def niche_config(self) -> object:
            raise ObjectDoesNotExist

    ctx.channel = _NoNiche()
    fake_output = VisualPromptsOutput(
        prompts=[VisualPrompt(scene_idx=0, prompt='plain aerial')],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'plain aerial' in result['prompts'][0]['prompt']  # type: ignore[index]


def test_visual_prompts_none_niche_skips_lore() -> None:
    """niche_config=None is treated as empty lore/angle."""
    from server.apps.pipelines.schemas import (
        VisualPrompt,
        VisualPromptsOutput,
    )

    ctx = _make_ctx()
    ctx.channel.niche_config = None
    fake_output = VisualPromptsOutput(
        prompts=[VisualPrompt(scene_idx=0, prompt='plain aerial')],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await VisualPromptsStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'plain aerial' in result['prompts'][0]['prompt']  # type: ignore[index]


def test_cast_locks_maps_approved_hero_ref() -> None:
    """Approved RunCast rows expose appearance text and hero_ref id."""
    import uuid

    from server.apps.pipelines.models import CastDesignStatus, RunCast
    from server.apps.pipelines.stages.visual_prompts import _cast_locks

    class _Row:
        design_status = CastDesignStatus.APPROVED
        draft_prompt = 'draft look'
        character = MagicMock()
        character.name = 'Marcus'
        character.appearance_prompt = 'grey beard'
        character.hero_ref_id = 'hero-ref-id'

    class _Unapproved:
        design_status = CastDesignStatus.PROPOSED
        draft_prompt = 'backup look'
        character = MagicMock()
        character.name = 'Livia'
        character.appearance_prompt = ''
        character.hero_ref_id = 'ignored-ref'

    class _Query:
        def select_related(self, *_args: object) -> '_Query':
            return self

        def __aiter__(self) -> object:
            async def _gen() -> object:
                yield _Row()
                yield _Unapproved()

            return _gen()

    async def _inner() -> dict[str, dict[str, str | None]]:
        with patch.object(
            RunCast.objects,
            'filter',
            return_value=_Query(),
        ):
            return await _cast_locks(uuid.uuid4())

    mapping = asyncio.run(_inner())
    assert mapping['marcus']['appearance_prompt'] == 'grey beard'
    assert mapping['marcus']['character_ref_id'] == 'hero-ref-id'
    assert mapping['livia']['appearance_prompt'] == 'backup look'
    assert mapping['livia']['character_ref_id'] is None


def test_lock_prompt_without_scene_still_applies_lore() -> None:
    """Missing scene metadata still prepends channel lore."""
    from server.apps.pipelines.schemas import VisualPrompt
    from server.apps.pipelines.stages.visual_prompts import (
        _attach_character_ref,
        _lock_prompt,
    )

    prompt = VisualPrompt(scene_idx=0, prompt='aerial')
    locked = _lock_prompt(
        prompt=prompt,
        scene=None,
        visual_bible='cinematic',
        angle='',
        appearance_by_name={},
        style_negatives=[],
    )
    assert 'cinematic' in locked.prompt
    unchanged = _attach_character_ref(locked, None, {})
    assert unchanged.character_ref_id is None
    no_ref = _attach_character_ref(
        locked,
        {'foreground_cast': ['Nobody']},
        {},
    )
    assert no_ref.character_ref_id is None
