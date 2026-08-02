"""Tests for CaptionBundleStage."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.caption_bundle import (
    CaptionBundleStage,
    _fetch_asset_bytes,
    _guess_mime,
    _load_approved_candidates,
    _load_manifest,
    _per_candidate_srt_bytes,
    _run_clipping,
    _run_longform,
    _word_alignment_payload,
    _words_in_range,
)

_MODULE = 'server.apps.pipelines.stages.caption_bundle'


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


def test_caption_bundle_attributes() -> None:
    assert CaptionBundleStage.key == 'caption_bundle'
    assert CaptionBundleStage.queue == 'api'


def test_caption_bundle_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'caption_bundle' in STAGE_REGISTRY


class TestGuessMime:
    """Tests for _guess_mime."""

    def test_srt(self) -> None:
        """A .srt filename maps to application/x-subrip."""
        assert _guess_mime('captions.srt') == 'application/x-subrip'

    def test_ass(self) -> None:
        """A .ass filename maps to text/x-ssa."""
        assert _guess_mime('captions.ass') == 'text/x-ssa'

    def test_json(self) -> None:
        """A .json filename maps to application/json."""
        assert _guess_mime('word_alignment.json') == 'application/json'

    def test_txt(self) -> None:
        """A .txt filename maps to text/plain."""
        assert _guess_mime('full_transcript.txt') == 'text/plain'

    def test_unknown_extension_defaults_to_octet_stream(self) -> None:
        """An unrecognized extension defaults to application/octet-stream."""
        assert _guess_mime('file.xyz') == 'application/octet-stream'


class TestFetchAssetBytes:
    """Tests for _fetch_asset_bytes."""

    def test_reads_asset_file(self) -> None:
        """Bytes are read from the fetched Asset's file field."""
        mock_asset = MagicMock()
        mock_asset.file.read.return_value = b'raw-bytes'

        async def _inner() -> bytes:
            with patch('server.apps.assets.models.Asset') as mock_cls:
                mock_cls.objects.aget = AsyncMock(return_value=mock_asset)
                return await _fetch_asset_bytes('asset-1')

        assert asyncio.run(_inner()) == b'raw-bytes'


class TestWordAlignmentPayload:
    """Tests for _word_alignment_payload."""

    def test_flattens_scene_fields(self) -> None:
        """Each scene is flattened to scene_idx/chapter_idx/start/end/words."""
        scenes = [
            {
                'scene_idx': 0,
                'chapter_idx': 1,
                'start_s': 0.0,
                'end_s': 1.0,
                'words': [{'word': 'hi'}],
            },
        ]
        result = _word_alignment_payload(scenes)
        assert result == [
            {
                'scene_idx': 0,
                'chapter_idx': 1,
                'start_s': 0.0,
                'end_s': 1.0,
                'words': [{'word': 'hi'}],
            },
        ]

    def test_missing_words_defaults_to_empty_list(self) -> None:
        """A scene without a words field defaults to an empty list."""
        result = _word_alignment_payload([{'scene_idx': 0}])
        assert result[0]['words'] == []


class TestRunLongform:
    """Tests for _run_longform."""

    def test_all_fields_present(self) -> None:
        """SRT, ASS, and word_alignment.json are all produced when present."""
        ctx = MagicMock()
        ctx.upstream = {
            'alignment': {
                'srt_asset_id': 'srt-1',
                'ass_asset_id': 'ass-1',
                'scenes': [{'scene_idx': 0}],
            },
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(side_effect=[b'srt-bytes', b'ass-bytes']),
            ):
                return await _run_longform(ctx)

        files = asyncio.run(_inner())
        assert files['captions.srt'] == b'srt-bytes'
        assert files['captions.ass'] == b'ass-bytes'
        assert json.loads(files['word_alignment.json'])[0]['scene_idx'] == 0

    def test_no_fields_present(self) -> None:
        """A missing alignment output produces no caption files."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _run_longform(ctx)

        assert asyncio.run(_inner()) == {}


class TestLoadManifest:
    """Tests for _load_manifest."""

    def test_parses_json_from_asset(self) -> None:
        """The manifest asset's bytes are fetched and JSON-decoded."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_transcribe': {'manifest_asset_id': 'manifest-1'},
        }
        raw = json.dumps({'transcript_text': 'hi'}).encode()

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=raw),
            ):
                return await _load_manifest(ctx)

        assert asyncio.run(_inner()) == {'transcript_text': 'hi'}


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


class TestWordsInRange:
    """Tests for _words_in_range."""

    def test_selects_and_rezeros_overlapping_words(self) -> None:
        """Overlapping words are selected and re-zeroed to the clip start."""
        words = [
            {'word': 'a', 'start': 0.0, 'end': 1.0},
            {'word': 'b', 'start': 5.0, 'end': 6.0},
            {'word': 'c', 'start': 10.0, 'end': 11.0},
        ]
        result = _words_in_range(words, start_sec=4.0, end_sec=8.0)
        assert len(result) == 1
        assert result[0]['word'] == 'b'
        assert result[0]['start'] == 1.0
        assert result[0]['end'] == 2.0

    def test_clamps_negative_rezeroed_times_to_zero(self) -> None:
        """A word starting before the window is clamped to zero, not negative."""
        words = [{'word': 'a', 'start': 3.0, 'end': 6.0}]
        result = _words_in_range(words, start_sec=4.0, end_sec=8.0)
        assert result[0]['start'] == 0.0
        assert result[0]['end'] == 2.0

    def test_equal_bounds_raises(self) -> None:
        """end_sec == start_sec violates the precondition assertion."""
        with pytest.raises(AssertionError):
            _words_in_range([], start_sec=1.0, end_sec=1.0)


class TestPerCandidateSrtBytes:
    """Tests for _per_candidate_srt_bytes."""

    def test_builds_one_srt_per_candidate(self) -> None:
        """One sliced SRT is built per approved candidate, keyed by id."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_approval_gate': {'approved_candidate_ids': ['cand-1']},
        }
        candidate = MagicMock()
        candidate.id = 'cand-1'
        candidate.start_sec = 0.0
        candidate.end_sec = 2.0
        words = [
            {'word': 'Hi', 'start': 0.0, 'end': 0.5, 'speaker_id': 'A'},
        ]

        async def _inner() -> dict:
            with patch('server.apps.clips.models.ClipCandidate') as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([candidate])
                mock_cls.objects.filter.return_value = qs
                return await _per_candidate_srt_bytes(ctx, words)

        result = asyncio.run(_inner())
        assert list(result) == ['cand-1']
        assert b'Hi' in result['cand-1']

    def test_no_candidates_returns_empty(self) -> None:
        """No approved candidates returns an empty mapping."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _per_candidate_srt_bytes(ctx, [])

        assert asyncio.run(_inner()) == {}


class TestRunClipping:
    """Tests for _run_clipping."""

    def test_builds_transcript_and_per_candidate_files(self) -> None:
        """Full transcript files and per-candidate SRTs are both produced."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_transcribe': {'manifest_asset_id': 'manifest-1'},
        }
        manifest = {
            'transcript_text': 'Hello world',
            'enriched_transcript': [
                {'word': 'Hello', 'start': 0.0, 'end': 0.4, 'speaker_id': 'A'},
            ],
        }

        async def _inner() -> tuple:
            with patch(
                f'{_MODULE}._load_manifest',
                new=AsyncMock(return_value=manifest),
            ):
                return await _run_clipping(ctx)

        files, per_candidate = asyncio.run(_inner())
        assert files['full_transcript.txt'] == b'Hello world'
        assert b'Hello' in files['full_transcript.srt']
        assert (
            json.loads(files['word_alignment.json'])
            == (manifest['enriched_transcript'])
        )
        assert per_candidate == {}


class TestCaptionBundleStageRun:
    """Tests for CaptionBundleStage.run."""

    def test_longform_run_saves_subtitle_and_doc_assets(self) -> None:
        """SRT/ASS save as SUBTITLE; word_alignment.json saves as DOC."""
        ctx = MagicMock()
        ctx.upstream = {
            'alignment': {
                'srt_asset_id': 'srt-1',
                'ass_asset_id': 'ass-1',
                'scenes': [{'scene_idx': 0}],
            },
        }
        assets = [MagicMock(id=f'asset-{i}') for i in range(3)]
        ctx.assets.save = AsyncMock(side_effect=assets)

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(side_effect=[b'srt', b'ass']),
            ):
                return await CaptionBundleStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['kind'] == 'longform'
        assert result['captions_srt_asset_id'] == 'asset-0'
        assert result['captions_ass_asset_id'] == 'asset-1'
        assert result['word_alignment_json_asset_id'] == 'asset-2'
        assert 'per_candidate_srt_asset_ids' not in result

    def test_clipping_run_saves_per_candidate_srts(self) -> None:
        """Clipping saves full transcript files plus per-candidate SRTs."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_ingest': {},
            'clip_transcribe': {'manifest_asset_id': 'manifest-1'},
            'clip_approval_gate': {'approved_candidate_ids': ['cand-1']},
        }
        manifest = {
            'transcript_text': 'Hello world',
            'enriched_transcript': [
                {'word': 'Hello', 'start': 0.0, 'end': 0.4, 'speaker_id': 'A'},
            ],
        }
        candidate = MagicMock()
        candidate.id = 'cand-1'
        candidate.start_sec = 0.0
        candidate.end_sec = 1.0
        assets = [MagicMock(id=f'asset-{i}') for i in range(4)]
        ctx.assets.save = AsyncMock(side_effect=assets)

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}._load_manifest',
                    new=AsyncMock(return_value=manifest),
                ),
                patch('server.apps.clips.models.ClipCandidate') as mock_cls,
            ):
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([candidate])
                mock_cls.objects.filter.return_value = qs
                return await CaptionBundleStage().run(ctx)

        result = asyncio.run(_inner())
        assert result['kind'] == 'clipping'
        assert result['full_transcript_srt_asset_id'] == 'asset-0'
        assert result['full_transcript_txt_asset_id'] == 'asset-1'
        assert result['word_alignment_json_asset_id'] == 'asset-2'
        assert result['per_candidate_srt_asset_ids'] == {'cand-1': 'asset-3'}
