"""Tests for EditorBriefStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.schemas import (
    EditorBriefBeatNote,
    EditorBriefOutput,
)
from server.apps.pipelines.stages.editor_brief import (
    EditorBriefStage,
    _build_clipping_appendix,
    _build_longform_appendix,
    _candidate_line,
    _chapter_lines,
    _fmt_mmss,
    _load_approved_candidates,
    _music_lines,
    _render_editorial_markdown,
    _scene_lines,
)


class _AsyncIter:
    """Minimal async iterator helper for mocking queryset iteration."""

    def __init__(self, items: list) -> None:
        self._items = iter(items)

    def __aiter__(self) -> '_AsyncIter':
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration from None


def _sample_editorial() -> EditorBriefOutput:
    return EditorBriefOutput(
        summary='Open on the hook; keep VO as master clock.',
        tone_and_pacing='Measured documentary pace; lift energy after mid.',
        must_hit_beats=['Opening cold open', 'Midpoint reveal'],
        optional_emphasis=['B-roll of maps'],
        caption_guidance='Chunk captions; emphasize key nouns.',
        music_and_silence='Bed under VO; dip on hero moments.',
        resolve_dos=['Import VO first', 'Use markers.csv for scenes'],
        resolve_donts=['Do not stretch motion to fill VO gaps'],
        beat_notes=[
            EditorBriefBeatNote(label='Scene 1', note='Hold wide longer.'),
        ],
    )


def test_editor_brief_attributes() -> None:
    assert EditorBriefStage.key == 'editor_brief'
    assert EditorBriefStage.queue == 'api'
    assert EditorBriefStage.max_retries == 3


def test_editor_brief_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'editor_brief' in STAGE_REGISTRY


class TestFmtMmss:
    """Tests for _fmt_mmss."""

    def test_zero(self) -> None:
        """Zero seconds formats as 0:00."""
        assert _fmt_mmss(0.0) == '0:00'

    def test_rounds_to_nearest_second(self) -> None:
        """Fractional seconds round to the nearest whole second."""
        assert _fmt_mmss(90.6) == '1:31'

    def test_negative_raises(self) -> None:
        """Negative seconds violate the precondition assertion."""
        with pytest.raises(AssertionError):
            _fmt_mmss(-1.0)


class TestChapterLines:
    """Tests for _chapter_lines."""

    def test_chapter_with_closing_line(self) -> None:
        """A chapter with a closing line renders both bullets."""
        lines = _chapter_lines([
            {'idx': 0, 'title': 'Rise', 'closing_line': 'The end.'},
        ])
        text = '\n'.join(lines)
        assert 'Appendix — Chapters' in text
        assert '**Rise**' in text
        assert 'Closing line: "The end."' in text

    def test_chapter_without_title_falls_back_to_index(self) -> None:
        """A missing title falls back to a 'Chapter {idx}' default."""
        lines = _chapter_lines([{'idx': 3}])
        assert '**Chapter 3**' in '\n'.join(lines)

    def test_chapter_without_closing_line_omits_bullet(self) -> None:
        """A chapter without a closing line has no closing-line bullet."""
        lines = _chapter_lines([{'idx': 0, 'title': 'Rise'}])
        assert not any('Closing line' in line for line in lines)

    def test_empty_chapters(self) -> None:
        """An empty chapter list still renders the section header."""
        lines = _chapter_lines([])
        assert lines[0] == '## Appendix — Chapters'


class TestSceneLines:
    """Tests for _scene_lines."""

    def test_hero_scene_flag_and_visual(self) -> None:
        """A hero scene is flagged and its visual concept is rendered."""
        lines = _scene_lines([
            {
                'idx': 1,
                'is_hero': True,
                'beat': 'The turn',
                'visual_concept': 'Wide shot',
            },
        ])
        text = '\n'.join(lines)
        assert 'Scene 1 (HERO): The turn' in text
        assert 'Visual: Wide shot' in text

    def test_non_hero_scene_without_visual(self) -> None:
        """A non-hero scene without a visual concept omits the visual bullet."""
        lines = _scene_lines([{'idx': 0, 'beat': 'Setup'}])
        text = '\n'.join(lines)
        assert '(HERO)' not in text
        assert 'Visual:' not in text

    def test_missing_beat_strips_trailing_colon(self) -> None:
        """A missing beat strips the trailing colon-space from the bullet."""
        lines = _scene_lines([{'idx': 0}])
        assert 'Scene 0' in lines[2]
        assert not lines[2].rstrip().endswith(':')

    def test_default_idx_uses_enumeration_index(self) -> None:
        """A missing idx falls back to the enumeration index."""
        lines = _scene_lines([{'beat': 'x'}, {'beat': 'y'}])
        text = '\n'.join(lines)
        assert 'Scene 0' in text
        assert 'Scene 1' in text


class TestMusicLines:
    """Tests for _music_lines."""

    def test_no_library_asset_id(self) -> None:
        """No selected bed renders a 'no music' notice."""
        lines = _music_lines({})
        assert 'No background music bed selected' in '\n'.join(lines)

    def test_with_library_asset_and_default_gain(self) -> None:
        """A selected bed without explicit gain uses the default gain."""
        lines = _music_lines({'library_asset_id': 'lib-1'})
        text = '\n'.join(lines)
        assert 'lib-1' in text
        assert '-22.0 dB' in text

    def test_with_custom_gain(self) -> None:
        """A selected bed with explicit gain renders that gain value."""
        lines = _music_lines({'library_asset_id': 'lib-1', 'gain_db': -10.0})
        assert '-10.0 dB' in '\n'.join(lines)


class TestBuildLongformAppendix:
    """Tests for _build_longform_appendix."""

    def test_full_upstream(self) -> None:
        """A fully populated upstream renders chapters, scenes, and music."""
        ctx = MagicMock()
        ctx.run.topic = 'My Topic'
        ctx.upstream = {
            'script': {'chapters': [{'idx': 0, 'title': 'Intro'}]},
            'scene_breakdown': {'scenes': [{'idx': 0, 'beat': 'Setup'}]},
            'music_plan': {'library_asset_id': 'lib-1'},
        }
        markdown = _build_longform_appendix(ctx)
        assert '**Intro**' in markdown
        assert 'Scene 0' in markdown
        assert 'lib-1' in markdown

    def test_missing_upstream_keys_use_defaults(self) -> None:
        """Missing upstream keys fall back to empty defaults, not errors."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {}
        markdown = _build_longform_appendix(ctx)
        assert 'No background music bed selected' in markdown


class TestCandidateLine:
    """Tests for _candidate_line."""

    def test_candidate_with_hook(self) -> None:
        """A candidate with a hook renders its hook line and scores."""
        candidate = MagicMock()
        candidate.start_sec = 10.0
        candidate.end_sec = 40.0
        candidate.title = 'Great Clip'
        candidate.hook_text = 'Watch this!'
        candidate.status = 'APPROVED'
        candidate.arrangement = 'contiguous'
        candidate.beats = [
            {
                'role': 'hook',
                'start_sec': 10.0,
                'end_sec': 15.0,
                'note': 'cold line',
            },
            {
                'role': 'story',
                'start_sec': 15.0,
                'end_sec': 30.0,
                'note': 'context',
            },
            {
                'role': 'payoff',
                'start_sec': 30.0,
                'end_sec': 40.0,
                'note': 'resolve',
            },
        ]
        candidate.relevance_score = 0.9
        candidate.virality_score = 0.8
        candidate.hook_score = 0.7
        line = _candidate_line(candidate)
        assert '**Great Clip**' in line
        assert 'envelope [0:10-0:40]' in line
        assert '(APPROVED, contiguous)' in line
        assert 'Hook overlay: "Watch this!"' in line
        assert 'Playback: Hook → Story → Payoff' in line
        assert '1. HOOK [0:10-0:15] - cold line' in line
        assert '2. STORY [0:15-0:30] - context' in line
        assert '3. PAYOFF [0:30-0:40] - resolve' in line
        assert 'relevance=0.90 virality=0.80 hook=0.70' in line

    def test_candidate_without_hook_omits_hook_line(self) -> None:
        """A candidate without a hook omits the hook bullet."""
        candidate = MagicMock()
        candidate.start_sec = 0.0
        candidate.end_sec = 5.0
        candidate.title = None
        candidate.hook_text = ''
        candidate.status = 'PROPOSED'
        candidate.arrangement = 'contiguous'
        candidate.beats = []
        candidate.relevance_score = 0.0
        candidate.virality_score = 0.0
        candidate.hook_score = 0.0
        line = _candidate_line(candidate)
        assert 'Untitled clip' in line
        assert 'Hook overlay:' not in line
        assert 'Playback: Hook → Story → Payoff' in line


class TestLoadApprovedCandidates:
    """Tests for _load_approved_candidates."""

    def test_no_approved_ids_returns_empty(self) -> None:
        """No approved candidate ids returns an empty list without a query."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> list:
            return await _load_approved_candidates(ctx)

        assert asyncio.run(_inner()) == []

    def test_returns_queried_candidates(self) -> None:
        """Approved ids trigger a filtered, ordered candidate query."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_approval_gate': {'approved_candidate_ids': ['id-1']},
        }
        fake_candidate = MagicMock()

        async def _inner() -> list:
            with patch(
                'server.apps.clips.models.ClipCandidate',
            ) as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([fake_candidate])
                mock_cls.objects.filter.return_value = qs
                return await _load_approved_candidates(ctx)

        result = asyncio.run(_inner())
        assert result == [fake_candidate]


class TestBuildClippingAppendix:
    """Tests for _build_clipping_appendix."""

    def test_no_candidates(self) -> None:
        """No approved candidates renders the 'none approved' notice."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {}

        async def _inner() -> str:
            return await _build_clipping_appendix(ctx)

        markdown = asyncio.run(_inner())
        assert 'No candidates were approved' in markdown

    def test_with_candidates(self) -> None:
        """Approved candidates each render their own bullet."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {
            'clip_approval_gate': {'approved_candidate_ids': ['id-1']},
        }
        fake_candidate = MagicMock()
        fake_candidate.start_sec = 0.0
        fake_candidate.end_sec = 10.0
        fake_candidate.title = 'Clip A'
        fake_candidate.hook_text = ''
        fake_candidate.status = 'APPROVED'
        fake_candidate.relevance_score = 1.0
        fake_candidate.virality_score = 1.0
        fake_candidate.hook_score = 1.0

        async def _inner() -> str:
            with patch(
                'server.apps.clips.models.ClipCandidate',
            ) as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([fake_candidate])
                mock_cls.objects.filter.return_value = qs
                return await _build_clipping_appendix(ctx)

        markdown = asyncio.run(_inner())
        assert '**Clip A**' in markdown


class TestRenderEditorialMarkdown:
    """Tests for _render_editorial_markdown."""

    def test_renders_all_sections(self) -> None:
        """Editorial output becomes a Resolve-facing markdown front matter."""
        text = _render_editorial_markdown('My Topic', _sample_editorial())
        assert '# Edit Brief — My Topic' in text
        assert '## Editorial summary' in text
        assert 'Open on the hook' in text
        assert 'Must-hit beats' in text
        assert 'Opening cold open' in text
        assert 'Caption guidance' in text
        assert 'Resolve — do' in text
        assert 'Resolve — do not' in text
        assert '**Scene 1**: Hold wide longer.' in text

    def test_empty_optional_sections(self) -> None:
        """Empty optional fields still render required sections."""
        editorial = EditorBriefOutput(
            summary='Summary only.',
            tone_and_pacing='Even.',
        )
        text = _render_editorial_markdown('T', editorial)
        assert 'Summary only.' in text
        assert '(none)' in text
        assert '## Caption guidance' not in text


class TestEditorBriefStageRun:
    """Tests for EditorBriefStage.run."""

    def test_longform_run(self) -> None:
        """Longform run saves DOC with editorial + appendix and kind."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.run.prompt_snapshot = {}
        ctx.upstream = {
            'script': {'chapters': []},
            'scene_breakdown': {'scenes': []},
            'music_plan': {},
        }
        ctx.prompts.render = AsyncMock(return_value=('', ''))
        ctx.prompts.get_model = AsyncMock(return_value=None)
        fake_asset = MagicMock()
        fake_asset.id = 'brief-uuid'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner() -> dict:
            with patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=_sample_editorial()),
            ):
                return await EditorBriefStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['brief_asset_id'] == 'brief-uuid'
        assert result['kind'] == 'longform'
        assert result['editorial']['summary'].startswith('Open on the hook')
        saved = ctx.assets.save.call_args.kwargs['content'].decode()
        assert 'Editorial summary' in saved
        assert 'Appendix — Chapters' in saved
        assert '---' in saved

    def test_clipping_run(self) -> None:
        """Clipping run saves DOC and reports kind=clipping."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.run.prompt_snapshot = {}
        ctx.upstream = {'clip_ingest': {}}
        ctx.prompts.render = AsyncMock(return_value=('', ''))
        ctx.prompts.get_model = AsyncMock(return_value=None)
        fake_asset = MagicMock()
        fake_asset.id = 'brief-uuid-2'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner() -> dict:
            with (
                patch(
                    'server.apps.clips.models.ClipCandidate',
                ) as mock_cls,
                patch(
                    'server.apps.generation.clients.llm.run_agent',
                    new=AsyncMock(return_value=_sample_editorial()),
                ),
            ):
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([])
                mock_cls.objects.filter.return_value = qs
                return await EditorBriefStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['kind'] == 'clipping'
        assert result['brief_asset_id'] == 'brief-uuid-2'
        saved = ctx.assets.save.call_args.kwargs['content'].decode()
        assert 'Appendix — Approved Candidates' in saved
