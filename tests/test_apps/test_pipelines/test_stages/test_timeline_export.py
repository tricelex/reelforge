"""Tests for TimelineExportStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.logic.scene_timing import (
    estimated_scene_windows as _estimated_scene_windows,
)
from server.apps.pipelines.stages.timeline_export import (
    TimelineExportStage,
    _build_clipping_files,
    _build_longform_files,
    _candidate_dict,
    _guess_mime,
    _load_approved_candidates,
    _markers_csv_rows,
    _resolve_scene_windows,
    _scene_breakdown_map,
    _shot_list_rows,
    _write_csv,
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
            raise StopAsyncIteration


def test_timeline_export_attributes() -> None:
    assert TimelineExportStage.key == 'timeline_export'
    assert TimelineExportStage.queue == 'api'


def test_timeline_export_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'timeline_export' in STAGE_REGISTRY


class TestGuessMime:
    """Tests for _guess_mime."""

    def test_csv(self) -> None:
        """A .csv filename maps to text/csv."""
        assert _guess_mime('markers.csv') == 'text/csv'

    def test_json(self) -> None:
        """A .json filename maps to application/json."""
        assert _guess_mime('candidates.json') == 'application/json'

    def test_other_defaults_to_plain_text(self) -> None:
        """Any other extension defaults to text/plain."""
        assert _guess_mime('markers.edl') == 'text/plain'


class TestWriteCsv:
    """Tests for _write_csv."""

    def test_header_and_rows_written(self) -> None:
        """The header row and data rows are written with LF line endings."""
        content = _write_csv(['a', 'b'], [['1', '2']]).decode()
        assert content == 'a,b\n1,2\n'


class TestEstimatedSceneWindows:
    """Tests for _estimated_scene_windows."""

    def test_cumulative_windows_ordered_by_idx(self) -> None:
        """Scenes are ordered by idx and given cumulative start/end times."""
        scenes = [
            {'idx': 1, 'est_seconds': 5.0},
            {'idx': 0, 'est_seconds': 10.0},
        ]
        windows = _estimated_scene_windows(scenes)
        assert windows[0]['scene_idx'] == 0
        assert windows[0]['start_s'] == 0.0
        assert windows[0]['end_s'] == 10.0
        assert windows[1]['scene_idx'] == 1
        assert windows[1]['start_s'] == 10.0
        assert windows[1]['end_s'] == 15.0

    def test_default_duration_when_missing(self) -> None:
        """A scene missing est_seconds defaults to 8.0 seconds."""
        windows = _estimated_scene_windows([{'idx': 0}])
        assert windows[0]['end_s'] == 8.0


class TestResolveSceneWindows:
    """Tests for _resolve_scene_windows."""

    def test_prefers_alignment_scenes(self) -> None:
        """Alignment scenes are used directly when present."""
        ctx = MagicMock()
        ctx.upstream = {
            'alignment': {
                'scenes': [{'scene_idx': 0, 'start_s': 1.0, 'end_s': 2.0}],
            },
        }
        result = _resolve_scene_windows(ctx)
        assert result == [{'scene_idx': 0, 'start_s': 1.0, 'end_s': 2.0}]

    def test_alignment_filters_non_dict_entries(self) -> None:
        """Non-dict entries in alignment scenes are filtered out."""
        ctx = MagicMock()
        ctx.upstream = {'alignment': {'scenes': [{'a': 1}, 'garbage']}}
        result = _resolve_scene_windows(ctx)
        assert result == [{'a': 1}]

    def test_falls_back_to_estimated_windows(self) -> None:
        """Missing/empty alignment falls back to estimated scene windows."""
        ctx = MagicMock()
        ctx.upstream = {
            'scene_breakdown': {'scenes': [{'idx': 0, 'est_seconds': 4.0}]},
        }
        result = _resolve_scene_windows(ctx)
        assert result[0]['scene_idx'] == 0
        assert result[0]['end_s'] == 4.0

    def test_falls_back_when_breakdown_scenes_not_a_list(self) -> None:
        """A non-list scene_breakdown.scenes value is treated as empty."""
        ctx = MagicMock()
        ctx.upstream = {'scene_breakdown': {'scenes': 'garbage'}}
        assert _resolve_scene_windows(ctx) == []

    def test_falls_back_when_no_upstream_at_all(self) -> None:
        """Completely empty upstream resolves to an empty scene list."""
        ctx = MagicMock()
        ctx.upstream = {}
        assert _resolve_scene_windows(ctx) == []


class TestSceneBreakdownMap:
    """Tests for _scene_breakdown_map."""

    def test_indexes_by_idx(self) -> None:
        """Scenes are indexed by their integer idx field."""
        ctx = MagicMock()
        ctx.upstream = {
            'scene_breakdown': {'scenes': [{'idx': 2, 'shot_type': 'wide'}]},
        }
        result = _scene_breakdown_map(ctx)
        assert result == {2: {'idx': 2, 'shot_type': 'wide'}}

    def test_empty_when_missing(self) -> None:
        """Missing scene_breakdown upstream yields an empty map."""
        ctx = MagicMock()
        ctx.upstream = {}
        assert _scene_breakdown_map(ctx) == {}


class TestMarkersCsvRows:
    """Tests for _markers_csv_rows."""

    def test_rows_include_timecodes_and_notes(self) -> None:
        """Each row includes name, timecodes, seconds, and truncated notes."""
        scenes = [
            {'scene_idx': 0, 'start_s': 0.0, 'end_s': 1.0, 'beat': 'Setup'},
        ]
        rows = _markers_csv_rows(scenes, fps=24.0)
        assert rows[0][0] == 'Scene 0'
        assert rows[0][3] == '0.000'
        assert rows[0][4] == '1.000'
        assert rows[0][5] == 'Setup'

    def test_prefers_text_over_beat(self) -> None:
        """The 'text' field is preferred over 'beat' for notes."""
        scenes = [
            {
                'scene_idx': 0,
                'start_s': 0.0,
                'end_s': 1.0,
                'text': 'Narration',
                'beat': 'Setup',
            },
        ]
        rows = _markers_csv_rows(scenes, fps=24.0)
        assert rows[0][5] == 'Narration'


class TestShotListRows:
    """Tests for _shot_list_rows."""

    def test_joins_timing_with_breakdown_detail(self) -> None:
        """Rows join scene timing with scene_breakdown detail by scene_idx."""
        scenes = [{'scene_idx': 0, 'start_s': 0.0, 'end_s': 2.0}]
        breakdown_map = {
            0: {
                'chapter_idx': 1,
                'shot_type': 'wide',
                'visual_concept': 'Sunset',
                'narration_text': 'Once upon a time',
            },
        }
        rows = _shot_list_rows(scenes, breakdown_map)
        assert rows[0] == [
            '0',
            '1',
            '0.000',
            '2.000',
            '2.000',
            'wide',
            'Sunset',
            'Once upon a time',
        ]

    def test_missing_detail_uses_scene_fallbacks(self) -> None:
        """Missing breakdown detail falls back to scene chapter_idx/text."""
        scenes = [
            {
                'scene_idx': 5,
                'start_s': 1.0,
                'end_s': 2.0,
                'chapter_idx': 3,
                'text': 'Fallback text',
            },
        ]
        rows = _shot_list_rows(scenes, {})
        assert rows[0][1] == '3'
        assert rows[0][-1] == 'Fallback text'


class TestBuildLongformFiles:
    """Tests for _build_longform_files."""

    def test_produces_three_files(self) -> None:
        """markers.csv, shot_list.csv, and markers.edl are all produced."""
        ctx = MagicMock()
        ctx.run.topic = 'My Run'
        ctx.upstream = {
            'scene_breakdown': {
                'scenes': [{'idx': 0, 'est_seconds': 5.0, 'shot_type': 'CU'}],
            },
        }
        files = _build_longform_files(ctx)
        assert set(files) == {'markers.csv', 'shot_list.csv', 'markers.edl'}
        assert b'Scene 0' in files['markers.csv']
        assert b'My Run' in files['markers.edl']


class TestLoadApprovedCandidates:
    """Tests for _load_approved_candidates."""

    def test_no_ids_returns_empty(self) -> None:
        """No approved candidate ids returns an empty list."""
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
            with patch('server.apps.clips.models.ClipCandidate') as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([fake_candidate])
                mock_cls.objects.filter.return_value = qs
                return await _load_approved_candidates(ctx)

        assert asyncio.run(_inner()) == [fake_candidate]


def _fake_candidate() -> MagicMock:
    candidate = MagicMock()
    candidate.id = 'cand-1'
    candidate.title = 'Great Clip'
    candidate.hook_text = 'Hook!'
    candidate.start_sec = 1.0
    candidate.end_sec = 5.0
    candidate.duration_sec = 4.0
    candidate.status = 'APPROVED'
    candidate.relevance_score = 0.5
    candidate.virality_score = 0.6
    candidate.hook_score = 0.7
    candidate.arrangement = 'contiguous'
    candidate.beats = [
        {
            'role': 'hook',
            'start_sec': 1.0,
            'end_sec': 2.0,
            'label': '',
            'note': '',
        },
        {
            'role': 'story',
            'start_sec': 2.0,
            'end_sec': 4.0,
            'label': '',
            'note': '',
        },
        {
            'role': 'payoff',
            'start_sec': 4.0,
            'end_sec': 5.0,
            'label': '',
            'note': '',
        },
    ]
    return candidate


class TestCandidateDict:
    """Tests for _candidate_dict."""

    def test_serializes_all_fields(self) -> None:
        """All candidate fields are copied into the plain dict."""
        result = _candidate_dict(_fake_candidate())
        assert result['id'] == 'cand-1'
        assert result['title'] == 'Great Clip'
        assert result['duration_sec'] == 4.0
        assert result['arrangement'] == 'contiguous'
        assert len(result['beats']) == 3


class TestBuildClippingFiles:
    """Tests for _build_clipping_files."""

    def test_no_candidates(self) -> None:
        """No approved candidates still produce all three (empty) files."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _build_clipping_files(ctx)

        files = asyncio.run(_inner())
        assert set(files) == {
            'candidates.json',
            'candidates.csv',
            'markers.edl',
        }
        assert files['candidates.json'] == b'[]'

    def test_with_candidates(self) -> None:
        """Approved candidates populate JSON, CSV, and EDL exports."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {
            'clip_approval_gate': {'approved_candidate_ids': ['cand-1']},
        }

        async def _inner() -> dict:
            with patch('server.apps.clips.models.ClipCandidate') as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([_fake_candidate()])
                mock_cls.objects.filter.return_value = qs
                return await _build_clipping_files(ctx)

        files = asyncio.run(_inner())
        assert b'Great Clip' in files['candidates.csv']
        assert b'cand-1' in files['candidates.json']
        assert b'HOOK' in files['markers.edl']
        assert b'STORY' in files['markers.edl']
        assert b'PAYOFF' in files['markers.edl']


class TestTimelineExportStageRun:
    """Tests for TimelineExportStage.run."""

    def test_longform_run_saves_all_files(self) -> None:
        """A longform upstream saves markers/shot_list/EDL as DOC assets."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {
            'scene_breakdown': {'scenes': [{'idx': 0, 'est_seconds': 5.0}]},
        }
        assets = [MagicMock(id=f'asset-{i}') for i in range(3)]
        ctx.assets.save = AsyncMock(side_effect=assets)

        async def _inner() -> dict:
            return await TimelineExportStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['kind'] == 'longform'
        assert result['markers_csv_asset_id'] == 'asset-0'
        assert result['shot_list_csv_asset_id'] == 'asset-1'
        assert result['markers_edl_asset_id'] == 'asset-2'

    def test_clipping_run_saves_all_files(self) -> None:
        """A clipping upstream saves candidates/EDL as DOC assets."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.upstream = {'clip_ingest': {}}
        assets = [MagicMock(id=f'asset-{i}') for i in range(3)]
        ctx.assets.save = AsyncMock(side_effect=assets)

        async def _inner() -> dict:
            with patch('server.apps.clips.models.ClipCandidate') as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([])
                mock_cls.objects.filter.return_value = qs
                return await TimelineExportStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['kind'] == 'clipping'
        assert result['candidates_json_asset_id'] == 'asset-0'
        assert result['candidates_csv_asset_id'] == 'asset-1'
        assert result['markers_edl_asset_id'] == 'asset-2'
