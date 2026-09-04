"""Tests for PackageZipStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.package_zip import (
    PackageZipStage,
    _build_role_asset_map,
    _copy_by_field_map,
    _ext_for_mime,
    _fetch_asset,
    _fetch_asset_bytes,
    _gather_candidates,
    _gather_clipping_captions,
    _gather_clipping_docs,
    _gather_clipping_files,
    _gather_longform_captions,
    _gather_longform_docs,
    _gather_longform_files,
    _gather_stills,
    _gather_thumbnails,
    _gather_timeline,
    _gather_video_scenes,
    _gather_vo,
    _outline_markdown,
    _script_markdown,
)
from server.common.exceptions import FatalProviderError

_MODULE = 'server.apps.pipelines.stages.package_zip'


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


def test_package_zip_attributes() -> None:
    assert PackageZipStage.key == 'package_zip'
    assert PackageZipStage.queue == 'render'
    assert PackageZipStage.timeout_s == 3600


def test_package_zip_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'package_zip' in STAGE_REGISTRY


class TestExtForMime:
    """Tests for _ext_for_mime."""

    def test_known_mime(self) -> None:
        """A known MIME type maps to its extension."""
        assert _ext_for_mime('image/png') == 'png'

    def test_unknown_mime_defaults_to_bin(self) -> None:
        """An unrecognized MIME type defaults to 'bin'."""
        assert _ext_for_mime('application/x-unknown') == 'bin'


class TestFetchHelpers:
    """Tests for _fetch_asset / _fetch_asset_bytes."""

    def test_fetch_asset_returns_asset(self) -> None:
        """_fetch_asset awaits Asset.objects.aget by id."""
        fake_asset = MagicMock()

        async def _inner() -> object:
            with patch('server.apps.assets.models.Asset') as mock_cls:
                mock_cls.objects.aget = AsyncMock(return_value=fake_asset)
                return await _fetch_asset('asset-1')

        assert asyncio.run(_inner()) is fake_asset

    def test_fetch_asset_bytes_reads_file(self) -> None:
        """_fetch_asset_bytes reads bytes from the fetched Asset's file."""
        fake_asset = MagicMock()
        fake_asset.file.read.return_value = b'content'

        async def _inner() -> bytes:
            with patch(
                f'{_MODULE}._fetch_asset',
                new=AsyncMock(
                    return_value=fake_asset,
                ),
            ):
                return await _fetch_asset_bytes('asset-1')

        assert asyncio.run(_inner()) == b'content'


class TestBuildRoleAssetMap:
    """Tests for _build_role_asset_map."""

    def test_maps_scene_idx_to_asset_id(self) -> None:
        """Succeeded child executions populate {scene_idx: asset_id}."""
        ctx = MagicMock()
        ctx.run.blueprint_snapshot = {}
        child = MagicMock()
        child.output = {'scene_idx': 2, 'asset_id': 'asset-2'}

        async def _inner() -> dict:
            with patch(
                'server.apps.pipelines.models.StageExecution',
            ) as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter([child])
                mock_cls.objects.filter.return_value = qs
                return await _build_role_asset_map(ctx, 'segment_stage')

        result = asyncio.run(_inner())
        assert result == {2: 'asset-2'}

    def test_skips_children_missing_scene_idx_or_asset_id(self) -> None:
        """Children lacking scene_idx or asset_id are skipped."""
        ctx = MagicMock()
        ctx.run.blueprint_snapshot = {}
        child_missing_scene = MagicMock()
        child_missing_scene.output = {'asset_id': 'asset-x'}
        child_missing_asset = MagicMock()
        child_missing_asset.output = {'scene_idx': 0}

        async def _inner() -> dict:
            with patch(
                'server.apps.pipelines.models.StageExecution',
            ) as mock_cls:
                qs = MagicMock()
                qs.order_by.return_value = _AsyncIter(
                    [child_missing_scene, child_missing_asset],
                )
                mock_cls.objects.filter.return_value = qs
                return await _build_role_asset_map(ctx, 'source_stage')

        assert asyncio.run(_inner()) == {}


class TestCopyByFieldMap:
    """Tests for _copy_by_field_map."""

    def test_copies_present_fields_only(self) -> None:
        """Only populated fields are fetched and copied to their target path."""
        output = {'a_asset_id': 'asset-a', 'b_asset_id': None}

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'bytes-a'),
            ):
                return await _copy_by_field_map(
                    output,
                    {'a_asset_id': 'path/a', 'b_asset_id': 'path/b'},
                )

        result = asyncio.run(_inner())
        assert result == {'path/a': b'bytes-a'}


class TestScriptMarkdown:
    """Tests for _script_markdown."""

    def test_renders_chapters(self) -> None:
        """Each chapter renders a heading and its stripped text."""
        script = {
            'chapters': [
                {'idx': 0, 'title': 'Intro', 'text': '  Hello there  '},
            ],
        }
        markdown = _script_markdown(script)
        assert '## Chapter 0: Intro' in markdown
        assert 'Hello there' in markdown

    def test_empty_script(self) -> None:
        """An empty script still renders the top-level heading."""
        assert _script_markdown({}) == '# Script\n'


class TestOutlineMarkdown:
    """Tests for _outline_markdown."""

    def test_renders_chapter_bullets(self) -> None:
        """Each chapter renders a bullet with title and retention device."""
        outline = {
            'chapters': [
                {'title': 'Rise', 'retention_device': 'cliffhanger'},
            ],
        }
        markdown = _outline_markdown(outline)
        assert '**Rise** — cliffhanger' in markdown

    def test_empty_outline(self) -> None:
        """An empty outline still renders the top-level heading."""
        assert _outline_markdown({}) == '# Outline\n'


class TestGatherLongformDocs:
    """Tests for _gather_longform_docs."""

    def test_missing_brief_raises(self) -> None:
        """A missing editor_brief output raises FatalProviderError."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _gather_longform_docs(ctx)

        with pytest.raises(FatalProviderError, match='editor_brief'):
            asyncio.run(_inner())

    def test_full_docs_with_script_and_outline(self) -> None:
        """Script and outline presence adds their own doc files."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.run.id = 'run-id'
        ctx.upstream = {
            'editor_brief': {'brief_asset_id': 'brief-1'},
            'script': {'chapters': [{'idx': 0, 'title': 'A', 'text': 'x'}]},
            'scene_breakdown': {'scenes': []},
            'outline': {'chapters': [{'title': 'A', 'retention_device': 'd'}]},
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'BRIEF'),
            ):
                return await _gather_longform_docs(ctx)

        files = asyncio.run(_inner())
        assert files['docs/EDIT_BRIEF.md'] == b'BRIEF'
        assert 'docs/metadata.json' in files
        assert 'docs/script.md' in files
        assert 'docs/scene_composition.json' in files
        assert 'docs/outline.md' in files

    def test_minimal_docs_without_script_or_outline(self) -> None:
        """No script/outline upstream omits their optional doc files."""
        ctx = MagicMock()
        ctx.run.topic = 'Topic'
        ctx.run.id = 'run-id'
        ctx.upstream = {'editor_brief': {'brief_asset_id': 'brief-1'}}

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'BRIEF'),
            ):
                return await _gather_longform_docs(ctx)

        files = asyncio.run(_inner())
        assert 'docs/script.md' not in files
        assert 'docs/outline.md' not in files


class TestGatherVo:
    """Tests for _gather_vo."""

    def test_gathers_chapter_shards(self) -> None:
        """Each TTS chapter shard is fetched and keyed by chapter index."""
        ctx = MagicMock()

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}.load_tts_chapter_shards',
                    new=AsyncMock(
                        return_value=[
                            {'chapter_idx': 0, 'asset_id': 'audio-0'},
                        ],
                    ),
                ),
                patch(
                    f'{_MODULE}._fetch_asset_bytes',
                    new=AsyncMock(return_value=b'AUDIO'),
                ),
            ):
                return await _gather_vo(ctx)

        files = asyncio.run(_inner())
        assert files == {'audio/vo/ch_000.mp3': b'AUDIO'}


class TestGatherVideoScenesAndStills:
    """Tests for _gather_video_scenes and _gather_stills."""

    def test_gather_video_scenes(self) -> None:
        """Each scene in the segment role map is fetched into video/scenes."""
        ctx = MagicMock()

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}._build_role_asset_map',
                    new=AsyncMock(return_value={0: 'asset-0'}),
                ),
                patch(
                    f'{_MODULE}._fetch_asset_bytes',
                    new=AsyncMock(return_value=b'VIDEO'),
                ),
            ):
                return await _gather_video_scenes(ctx)

        files = asyncio.run(_inner())
        assert files == {'video/scenes/sc_0000.mp4': b'VIDEO'}

    def test_gather_stills(self) -> None:
        """Each still in the source role map is fetched with its mime ext."""
        ctx = MagicMock()
        fake_asset = MagicMock()
        fake_asset.mime = 'image/jpeg'

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}._build_role_asset_map',
                    new=AsyncMock(return_value={0: 'asset-0'}),
                ),
                patch(
                    f'{_MODULE}._fetch_asset',
                    new=AsyncMock(return_value=fake_asset),
                ),
                patch(
                    f'{_MODULE}.asyncio.to_thread',
                    new=AsyncMock(return_value=b'STILL'),
                ),
            ):
                return await _gather_stills(ctx)

        files = asyncio.run(_inner())
        assert files == {'stills/scenes/sc_0000.jpg': b'STILL'}


class TestGatherLongformCaptionsAndTimeline:
    """Tests for _gather_longform_captions and _gather_timeline."""

    def test_gather_longform_captions(self) -> None:
        """Populated caption_bundle fields copy to their captions/ paths."""
        ctx = MagicMock()
        ctx.upstream = {
            'caption_bundle': {'captions_srt_asset_id': 'srt-1'},
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'SRT'),
            ):
                return await _gather_longform_captions(ctx)

        assert asyncio.run(_inner()) == {'captions/captions.srt': b'SRT'}

    def test_gather_timeline(self) -> None:
        """Populated timeline_export fields copy to their timeline/ paths."""
        ctx = MagicMock()
        ctx.upstream = {
            'timeline_export': {'markers_csv_asset_id': 'markers-1'},
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'CSV'),
            ):
                return await _gather_timeline(ctx)

        assert asyncio.run(_inner()) == {'timeline/markers.csv': b'CSV'}


class TestGatherThumbnails:
    """Tests for _gather_thumbnails."""

    def test_gathers_candidates_with_asset_ids(self) -> None:
        """Thumbnail candidates with an asset_id are fetched and ranked."""
        ctx = MagicMock()
        ctx.upstream = {
            'thumbnail': {
                'candidates': [
                    {'asset_id': 'thumb-1', 'rank': 0},
                    {'rank': 1},
                ],
            },
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'THUMB'),
            ):
                return await _gather_thumbnails(ctx)

        assert asyncio.run(_inner()) == {
            'thumbnails/thumb_00.jpg': b'THUMB',
        }

    def test_no_thumbnail_upstream_returns_empty(self) -> None:
        """No thumbnail upstream output returns no thumbnail files."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _gather_thumbnails(ctx)

        assert asyncio.run(_inner()) == {}


class TestGatherLongformFiles:
    """Tests for _gather_longform_files (full integration)."""

    def test_assembles_all_sections(self) -> None:
        """All longform gather helpers are invoked and merged."""
        ctx = MagicMock()

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}._gather_longform_docs',
                    new=AsyncMock(return_value={'docs/a': b'1'}),
                ),
                patch(
                    f'{_MODULE}._gather_vo',
                    new=AsyncMock(return_value={'audio/vo/a': b'2'}),
                ),
                patch(
                    f'{_MODULE}._gather_video_scenes',
                    new=AsyncMock(return_value={'video/a': b'3'}),
                ),
                patch(
                    f'{_MODULE}._gather_stills',
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    f'{_MODULE}._gather_longform_captions',
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    f'{_MODULE}._gather_timeline',
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    f'{_MODULE}._gather_thumbnails',
                    new=AsyncMock(return_value={}),
                ),
            ):
                return await _gather_longform_files(ctx)

        files = asyncio.run(_inner())
        assert files == {
            'docs/a': b'1',
            'audio/vo/a': b'2',
            'video/a': b'3',
        }


class TestGatherClippingDocs:
    """Tests for _gather_clipping_docs."""

    def test_missing_brief_raises(self) -> None:
        """A missing editor_brief output raises FatalProviderError."""
        ctx = MagicMock()
        ctx.upstream = {}

        async def _inner() -> dict:
            return await _gather_clipping_docs(ctx)

        with pytest.raises(FatalProviderError, match='editor_brief'):
            asyncio.run(_inner())

    def test_with_scene_cuts(self) -> None:
        """A present scene_cuts value adds docs/scene_cuts.json."""
        ctx = MagicMock()
        ctx.upstream = {
            'editor_brief': {'brief_asset_id': 'brief-1'},
            'clip_transcribe': {'scene_cuts': [1.0, 2.0]},
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'BRIEF'),
            ):
                return await _gather_clipping_docs(ctx)

        files = asyncio.run(_inner())
        assert files['docs/EDIT_BRIEF.md'] == b'BRIEF'
        assert 'docs/scene_cuts.json' in files

    def test_without_scene_cuts(self) -> None:
        """No scene_cuts value omits docs/scene_cuts.json."""
        ctx = MagicMock()
        ctx.upstream = {'editor_brief': {'brief_asset_id': 'brief-1'}}

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'BRIEF'),
            ):
                return await _gather_clipping_docs(ctx)

        files = asyncio.run(_inner())
        assert 'docs/scene_cuts.json' not in files


class TestGatherCandidates:
    """Tests for _gather_candidates."""

    def test_copies_present_fields(self) -> None:
        """Populated timeline_export clipping fields copy to candidates/."""
        ctx = MagicMock()
        ctx.upstream = {
            'timeline_export': {'candidates_json_asset_id': 'cand-1'},
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'JSON'),
            ):
                return await _gather_candidates(ctx)

        assert asyncio.run(_inner()) == {
            'candidates/candidates.json': b'JSON',
        }


class TestGatherClippingCaptions:
    """Tests for _gather_clipping_captions."""

    def test_copies_fields_and_per_candidate_srts(self) -> None:
        """Full transcript fields and per-candidate SRTs are both gathered."""
        ctx = MagicMock()
        ctx.upstream = {
            'caption_bundle': {
                'full_transcript_srt_asset_id': 'srt-1',
                'per_candidate_srt_asset_ids': {'cand-1': 'srt-cand-1'},
            },
        }

        async def _inner() -> dict:
            with patch(
                f'{_MODULE}._fetch_asset_bytes',
                new=AsyncMock(return_value=b'SRT'),
            ):
                return await _gather_clipping_captions(ctx)

        files = asyncio.run(_inner())
        assert files['captions/full_transcript.srt'] == b'SRT'
        assert files['captions/per_candidate/cand-1.srt'] == b'SRT'

    def test_no_per_candidate_srts(self) -> None:
        """No per-candidate SRTs means only the top-level fields are copied."""
        ctx = MagicMock()
        ctx.upstream = {'caption_bundle': {}}

        async def _inner() -> dict:
            return await _gather_clipping_captions(ctx)

        assert asyncio.run(_inner()) == {}


class TestGatherClippingFiles:
    """Tests for _gather_clipping_files (full integration)."""

    def test_assembles_all_sections(self) -> None:
        """All clipping gather helpers are invoked and merged."""
        ctx = MagicMock()

        async def _inner() -> dict:
            with (
                patch(
                    f'{_MODULE}._gather_clipping_docs',
                    new=AsyncMock(return_value={'docs/a': b'1'}),
                ),
                patch(
                    f'{_MODULE}._gather_candidates',
                    new=AsyncMock(return_value={'candidates/a': b'2'}),
                ),
                patch(
                    f'{_MODULE}._gather_clipping_captions',
                    new=AsyncMock(return_value={}),
                ),
            ):
                return await _gather_clipping_files(ctx)

        files = asyncio.run(_inner())
        assert files == {
            'docs/a': b'1',
            'candidates/a': b'2',
        }


class TestPackageZipStageRun:
    """Tests for PackageZipStage.run."""

    def test_longform_run_saves_package_asset(self) -> None:
        """A longform run gathers files, builds a zip, and saves it."""
        ctx = MagicMock()
        ctx.upstream = {'editor_brief': {'brief_asset_id': 'b'}}
        ctx.run.id = 'run-uuid'
        fake_asset = MagicMock()
        fake_asset.id = 'package-asset-uuid'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner(mock_builder: MagicMock) -> dict:
            mock_builder.package_root_name.return_value = 'run_root'
            mock_builder.collect_source_asset_ids.return_value = {}
            mock_builder.build_readme.return_value = b'README'
            mock_builder.build_manifest.return_value = b'MANIFEST'
            mock_builder.build_zip.return_value = b'ZIPBYTES'
            return await PackageZipStage().run(ctx)

        with (
            patch(
                f'{_MODULE}._gather_longform_files',
                new=AsyncMock(return_value={'docs/a': b'1'}),
            ),
            patch(f'{_MODULE}.package_builder') as mock_builder,
        ):
            result = asyncio.run(_inner(mock_builder))

        assert result == {
            'package_asset_id': 'package-asset-uuid',
            'size_bytes': len(b'ZIPBYTES'),
            'entry_count': 3,
            'root_name': 'run_root',
        }
        ctx.assets.save.assert_awaited_once()
        assert ctx.assets.save.call_args.kwargs['filename'] == 'run_root.zip'
        mock_builder.package_root_name.assert_called_once_with(
            'run-uuid',
            is_clipping=False,
        )

    def test_clipping_run_saves_package_asset(self) -> None:
        """A clipping run gathers clipping files, builds a zip, and saves it."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_ingest': {},
            'editor_brief': {'brief_asset_id': 'b'},
        }
        ctx.run.id = 'run-uuid-2'
        fake_asset = MagicMock()
        fake_asset.id = 'package-asset-uuid-2'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner(mock_builder: MagicMock) -> dict:
            mock_builder.package_root_name.return_value = 'run_root_clip'
            mock_builder.collect_source_asset_ids.return_value = {}
            mock_builder.build_readme.return_value = b'README'
            mock_builder.build_manifest.return_value = b'MANIFEST'
            mock_builder.build_zip.return_value = b'ZIPBYTES2'
            return await PackageZipStage().run(ctx)

        with (
            patch(
                f'{_MODULE}._gather_clipping_files',
                new=AsyncMock(return_value={'candidates/a': b'1'}),
            ),
            patch(f'{_MODULE}.package_builder') as mock_builder,
        ):
            result = asyncio.run(_inner(mock_builder))

        assert result['root_name'] == 'run_root_clip'
        mock_builder.package_root_name.assert_called_once_with(
            'run-uuid-2',
            is_clipping=True,
        )
