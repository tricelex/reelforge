"""Tests for the narrative_qc stage (pre-render creative quality gate)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.narrative_qc import NarrativeQCStage
from server.common.exceptions import FatalProviderError


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.upstream = {
        'script': {
            'chapters': [
                {
                    'idx': 0,
                    'title': 'Intro',
                    'text': 'Rome was great.',
                    'word_count': 3,
                    'closing_line': 'But it fell.',
                    'commentary': 'I think this collapse was avoidable.',
                },
            ],
            'total_word_count': 3,
        },
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'beat': 'intro',
                    'narration_text': 'Rome was great once, long ago.',
                    'visual_concept': 'aerial Rome',
                    'shot_type': 'aerial',
                    'est_seconds': 8.0,
                    'is_hero': True,
                    'foreground_cast': [],
                    'word_count': 20,
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_narrative_qc_stage_key() -> None:
    assert NarrativeQCStage.key == 'narrative_qc'
    assert NarrativeQCStage.queue == 'api'


def test_narrative_qc_fan_out_none() -> None:
    assert NarrativeQCStage().fan_out(MagicMock()) is None


def test_narrative_qc_passes_through_on_high_score() -> None:
    from server.apps.pipelines.schemas import NarrativeQCOutput

    ctx = _make_ctx()
    fake_output = NarrativeQCOutput(passed=True, score=0.85, issues=[])

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await NarrativeQCStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['passed'] is True
    assert result['score'] == 0.85


def test_narrative_qc_raises_fatal_error_on_failed_score() -> None:
    from server.apps.pipelines.schemas import NarrativeQCOutput

    ctx = _make_ctx()
    fake_output = NarrativeQCOutput(
        passed=False,
        score=0.2,
        issues=['weak hook', 'no retention loops'],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await NarrativeQCStage().run(ctx)

    with pytest.raises(FatalProviderError, match='narrative_qc'):
        asyncio.run(_inner())
