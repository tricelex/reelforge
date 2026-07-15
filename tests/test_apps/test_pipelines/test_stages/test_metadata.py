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
                    'start_s': 0.5,
                    'end_s': 60.0,
                    'text': 'It fell...',
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_metadata_stage_key() -> None:
    """MetadataStage has the expected class attributes."""
    assert MetadataStage.key == 'metadata'
    assert MetadataStage.queue == 'api'


def test_metadata_fan_out_none() -> None:
    """Metadata is a single-execution stage."""
    assert MetadataStage().fan_out(MagicMock()) is None


def test_build_chapter_timestamps() -> None:
    """Chapter-relative scene times become absolute YouTube offsets."""
    scenes = [
        {'chapter_idx': 0, 'start_s': 0.1, 'end_s': 65.0},
        {'chapter_idx': 1, 'start_s': 0.2, 'end_s': 60.0},
    ]
    chapters = [
        {'idx': 0, 'title': 'The Beginning'},
        {'idx': 1, 'title': 'The Fall'},
    ]
    result = _build_chapter_timestamps(scenes, chapters)
    assert '0:00 The Beginning' in result
    # ch0 duration ≈ 64.9s → ch1 absolute start ≈ 1:04
    assert '1:04 The Fall' in result


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
    """Chapter duration is min(start)→max(end) across all scenes in chapter."""
    scenes = [
        {'chapter_idx': 0, 'start_s': 0.0, 'end_s': 10.0},
        {'chapter_idx': 0, 'start_s': 10.0, 'end_s': 90.0},
        {'chapter_idx': 1, 'start_s': 0.0, 'end_s': 30.0},
    ]
    chapters = [
        {'idx': 0, 'title': 'Intro'},
        {'idx': 1, 'title': 'Next'},
    ]
    result = _build_chapter_timestamps(scenes, chapters)
    assert '0:00 Intro' in result
    assert '1:30 Next' in result