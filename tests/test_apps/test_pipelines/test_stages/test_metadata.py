"""Tests for the metadata stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.metadata import (
    MetadataStage,
    _build_chapter_timestamps,
)


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'Fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.upstream = {
        'script': {
            'chapters': [
                {'idx': 0, 'title': 'The Beginning', 'word_count': 200},
                {'idx': 1, 'title': 'The Fall', 'word_count': 400},
            ],
        },
        'alignment': {
            'scenes': [
                {
                    'chapter_idx': 0,
                    'start_s': 0.0,
                    'end_s': 60.0,
                    'text': 'Rome...',
                },
                {
                    'chapter_idx': 1,
                    'start_s': 60.0,
                    'end_s': 120.0,
                    'text': 'It fell...',
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_metadata_stage_key() -> None:
    """MetadataStage has the expected class attributes."""
    assert MetadataStage.key == 'metadata'
    assert MetadataStage.queue == 'api'


def test_metadata_fan_out_none() -> None:
    """Metadata is a single-execution stage."""
    assert MetadataStage().fan_out(MagicMock()) is None


def test_build_chapter_timestamps() -> None:
    """Absolute scene starts become YouTube chapter offsets."""
    scenes = [
        {'chapter_idx': 0, 'start_s': 0.1, 'end_s': 65.0},
        {'chapter_idx': 1, 'start_s': 65.0, 'end_s': 125.0},
    ]
    chapters = [
        {'idx': 0, 'title': 'The Beginning'},
        {'idx': 1, 'title': 'The Fall'},
    ]
    result = _build_chapter_timestamps(scenes, chapters)
    assert '0:00 The Beginning' in result
    # ch0 has one scene → no transition pad; ch1 starts at 65s
    assert '1:05 The Fall' in result


def test_metadata_run_returns_title_and_tags() -> None:
    """run() returns dict with 'title', 'description', and 'tags'."""
    from server.apps.pipelines.schemas import VideoMetadata

    ctx = _make_ctx()
    fake_output = VideoMetadata(
        title='How Rome REALLY Fell (476 AD)',
        description="The full story of Rome's collapse.\n\n0:00 The Beginning",
        tags=['rome', 'history', 'documentary'],
        category='Education',
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await MetadataStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'title' in result
    assert len(result['title']) <= 60  # type: ignore[arg-type]
    assert 'description' in result
    assert 'tags' in result


def test_build_chapter_timestamps_empty_inputs() -> None:
    """_build_chapter_timestamps returns empty string for empty inputs."""
    result = _build_chapter_timestamps([], [])
    assert result == ''


def test_build_chapter_timestamps_chapter_without_scene() -> None:
    """Chapter without a matching scene stays at the current absolute offset."""
    scenes: list[dict[str, object]] = []  # no scenes for chapter 0
    chapters = [{'idx': 0, 'title': 'Orphan Chapter'}]
    result = _build_chapter_timestamps(scenes, chapters)
    assert '0:00 Orphan Chapter' in result


def test_build_chapter_timestamps_uses_span_across_scenes() -> None:
    """Multi-scene chapters add transition padding before the next chapter."""
    scenes = [
        {'chapter_idx': 0, 'start_s': 0.0, 'end_s': 10.0},
        {'chapter_idx': 0, 'start_s': 10.0, 'end_s': 90.0},
        {'chapter_idx': 1, 'start_s': 90.0, 'end_s': 120.0},
    ]
    chapters = [
        {'idx': 0, 'title': 'Intro'},
        {'idx': 1, 'title': 'Next'},
    ]
    result = _build_chapter_timestamps(scenes, chapters)
    assert '0:00 Intro' in result
    # 90s absolute + one 0.5s inter-scene transition in ch0
    assert '1:30 Next' in result


def test_description_gains_credits_for_documentary_runs() -> None:
    """Required attributions are appended to the YouTube description."""
    from server.apps.pipelines.logic.value_objects import (
        FootageCreditPayload,
        RunCreditsPayload,
    )
    from server.apps.pipelines.schemas import VideoMetadata

    ctx = _make_ctx()
    ctx.run.blueprint_snapshot = {'profile': 'documentary_footage'}
    run_credits = RunCreditsPayload(
        entries=[
            FootageCreditPayload(
                provider='wikimedia',
                license='CC-BY-4.0',
                license_url='https://creativecommons.org/licenses/by/4.0/',
                author='A Photographer',
                source_url='https://commons/x',
                title='A Photograph',
                attribution_required=True,
                scene_idxs=[0],
            ),
        ],
        truncated=False,
    )
    fake_output = VideoMetadata(
        title='How Rome REALLY Fell (476 AD)',
        description="The full story of Rome's collapse.\n\n0:00 The Beginning",
        tags=['rome', 'history', 'documentary'],
        category='Education',
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.metadata._load_credits',
                new=AsyncMock(return_value=run_credits),
            ),
        ):
            return await MetadataStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'A Photographer' in result['description']
    assert 'CC-BY-4.0' in result['description']


def test_metadata_run_falls_back_to_scene_breakdown_timing() -> None:
    """Without an alignment stage, timestamps come from scene_breakdown."""
    from server.apps.pipelines.schemas import VideoMetadata

    ctx = _make_ctx()
    ctx.upstream = {
        'script': {
            'chapters': [
                {'idx': 0, 'title': 'Night Opening'},
                {'idx': 1, 'title': 'Teaching'},
            ],
        },
        'scene_breakdown': {
            'scenes': [
                {'idx': 0, 'chapter_idx': 0, 'est_seconds': 12.0},
                {'idx': 1, 'chapter_idx': 1, 'est_seconds': 8.0},
            ],
        },
    }
    fake_output = VideoMetadata(
        title='Title',
        description='Body',
        tags=['a'],
    )
    captured: dict[str, object] = {}

    async def _fake_run_agent(
        _agent: object,
        user_prompt: str,
        *_args: object,
        **_kwargs: object,
    ) -> VideoMetadata:
        captured['user_prompt'] = user_prompt
        return fake_output

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(side_effect=_fake_run_agent),
        ):
            return await MetadataStage().run(ctx)

    asyncio.run(_inner())
    assert '0:00 Night Opening' in captured['user_prompt']  # type: ignore[operator]
    assert '0:12 Teaching' in captured['user_prompt']  # type: ignore[operator]


def test_description_is_unchanged_for_ai_visual_runs() -> None:
    """A longform_v1 run gets no credits block."""
    from server.apps.pipelines.schemas import VideoMetadata

    ctx = _make_ctx()
    ctx.run.blueprint_snapshot = {'stages': []}
    fake_output = VideoMetadata(
        title='How Rome REALLY Fell (476 AD)',
        description="The full story of Rome's collapse.\n\n0:00 The Beginning",
        tags=['rome', 'history', 'documentary'],
        category='Education',
    )

    async def _inner() -> dict[str, object]:
        loader = AsyncMock()
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.metadata._load_credits',
                new=loader,
            ),
        ):
            result = await MetadataStage().run(ctx)
        loader.assert_not_awaited()
        return result

    result = asyncio.run(_inner())
    assert 'Footage credits' not in result['description']
