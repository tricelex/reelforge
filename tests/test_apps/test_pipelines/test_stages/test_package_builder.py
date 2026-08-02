"""Tests for editor-package pure helpers (README/MANIFEST/zip assembly)."""

import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from server.apps.pipelines.services.package_builder import (
    README_CLIPPING,
    README_LONGFORM,
    build_manifest,
    build_readme,
    build_zip,
    collect_source_asset_ids,
    package_root_name,
    sha256_hex,
    short_run_id,
)


class TestSha256Hex:
    """Tests for sha256_hex."""

    def test_matches_hashlib(self) -> None:
        """The digest matches hashlib's own sha256 hexdigest."""
        content = b'hello world'
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_hex(content) == expected

    def test_digest_is_64_hex_chars(self) -> None:
        """The digest is always 64 hex characters long."""
        assert len(sha256_hex(b'')) == 64

    def test_non_bytes_content_raises(self) -> None:
        """Non-bytes content violates the precondition assertion."""
        with pytest.raises(AssertionError):
            sha256_hex('not bytes')  # type: ignore[arg-type]


class TestShortRunId:
    """Tests for short_run_id."""

    def test_strips_hyphens_and_truncates(self) -> None:
        """Hyphens are stripped and the result truncated to 8 chars."""
        run_id = '12345678-abcd-ef01-2345-6789abcdef01'
        assert short_run_id(run_id) == '12345678'

    def test_short_input_returned_as_is(self) -> None:
        """An input shorter than 8 hex chars is returned unchanged."""
        assert short_run_id('ab-cd') == 'abcd'

    def test_empty_run_id_raises(self) -> None:
        """An empty run_id violates the precondition assertion."""
        with pytest.raises(AssertionError):
            short_run_id('')

    def test_all_hyphens_raises(self) -> None:
        """A run_id containing only hyphens leaves no hex characters."""
        with pytest.raises(AssertionError):
            short_run_id('----')


class TestPackageRootName:
    """Tests for package_root_name."""

    def test_longform_suffix(self) -> None:
        """Non-clipping runs get the longform suffix."""
        name = package_root_name('12345678-0000', is_clipping=False)
        assert name == 'run_12345678_longform_editor_package'

    def test_clipping_suffix(self) -> None:
        """Clipping runs get the clip suffix."""
        name = package_root_name('12345678-0000', is_clipping=True)
        assert name == 'run_12345678_clip_editor_package'

    def test_empty_run_id_raises(self) -> None:
        """An empty run_id violates the precondition assertion."""
        with pytest.raises(AssertionError):
            package_root_name('', is_clipping=False)


class TestCollectSourceAssetIds:
    """Tests for collect_source_asset_ids."""

    def test_flattens_asset_id_fields(self) -> None:
        """Every ``*asset_id`` string field is flattened by stage.field."""
        upstream = {
            'editor_brief': {'brief_asset_id': 'brief-1'},
            'timeline_export': {
                'markers_csv_asset_id': 'markers-1',
                'kind': 'longform',
            },
        }
        ids = collect_source_asset_ids(upstream)
        assert ids == {
            'editor_brief.brief_asset_id': 'brief-1',
            'timeline_export.markers_csv_asset_id': 'markers-1',
        }

    def test_ignores_non_string_asset_id_values(self) -> None:
        """A non-string value on an ``*asset_id`` field is ignored."""
        upstream = {'stage': {'thumb_asset_id': 123}}
        assert collect_source_asset_ids(upstream) == {}

    def test_ignores_fields_not_ending_in_asset_id(self) -> None:
        """Fields that don't end in ``asset_id`` are ignored even if strings."""
        upstream = {'stage': {'kind': 'longform'}}
        assert collect_source_asset_ids(upstream) == {}

    def test_empty_upstream_returns_empty_dict(self) -> None:
        """An empty upstream dict returns an empty mapping."""
        assert collect_source_asset_ids({}) == {}

    def test_upstream_not_dict_raises(self) -> None:
        """A non-dict upstream violates the precondition assertion."""
        with pytest.raises(AssertionError):
            collect_source_asset_ids([])  # type: ignore[arg-type]

    def test_output_not_dict_raises(self) -> None:
        """A non-dict per-stage output violates the precondition assertion."""
        with pytest.raises(AssertionError):
            collect_source_asset_ids({'stage': 'not-a-dict'})  # type: ignore[dict-item]


class TestBuildReadme:
    """Tests for build_readme."""

    def test_longform_readme(self) -> None:
        """The longform README template is returned when not clipping."""
        assert build_readme(is_clipping=False) == README_LONGFORM.encode()

    def test_clipping_readme(self) -> None:
        """The clipping README template is returned when clipping."""
        assert build_readme(is_clipping=True) == README_CLIPPING.encode()


class TestBuildManifest:
    """Tests for build_manifest."""

    def test_manifest_structure(self) -> None:
        """The manifest lists every file's path/size/checksum, sorted."""
        files = {
            'b.txt': b'second',
            'a.txt': b'first',
        }
        raw = build_manifest(
            files,
            source_asset_ids={'stage.asset_id': 'abc'},
            root_name='run_root',
        )
        manifest = json.loads(raw)
        assert manifest['root_name'] == 'run_root'
        assert manifest['file_count'] == 2
        assert manifest['source_asset_ids'] == {'stage.asset_id': 'abc'}
        assert [f['path'] for f in manifest['files']] == ['a.txt', 'b.txt']
        assert manifest['files'][0]['size_bytes'] == len(b'first')
        assert manifest['files'][0]['sha256'] == sha256_hex(b'first')
        assert 'generated_at' in manifest

    def test_empty_files_raises(self) -> None:
        """An empty files mapping violates the precondition assertion."""
        with pytest.raises(AssertionError):
            build_manifest({}, source_asset_ids={}, root_name='root')

    def test_empty_root_name_raises(self) -> None:
        """An empty root_name violates the precondition assertion."""
        with pytest.raises(AssertionError):
            build_manifest(
                {'a.txt': b'x'},
                source_asset_ids={},
                root_name='',
            )


class TestBuildZip:
    """Tests for build_zip."""

    def test_zip_contains_all_entries_under_root(self) -> None:
        """Every file is written into the zip under the root folder name."""
        files = {'docs/a.txt': b'hello', 'docs/b.txt': b'world'}
        zip_bytes = build_zip(files, root_name='run_root')
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
            assert names == {
                'run_root/docs/a.txt',
                'run_root/docs/b.txt',
            }
            assert zf.read('run_root/docs/a.txt') == b'hello'

    def test_zip_contains_readme_and_manifest_when_assembled(self) -> None:
        """A full assembly (README + MANIFEST) round-trips through the zip."""
        files: dict[str, bytes] = {'docs/scene.json': b'{}'}
        files['README.md'] = build_readme(is_clipping=False)
        files['MANIFEST.json'] = build_manifest(
            files,
            source_asset_ids={},
            root_name='run_root',
        )
        zip_bytes = build_zip(files, root_name='run_root')
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
            assert 'run_root/README.md' in names
            assert 'run_root/MANIFEST.json' in names
            assert zf.read('run_root/README.md') == README_LONGFORM.encode()

    def test_empty_files_raises(self) -> None:
        """An empty files mapping violates the precondition assertion."""
        with pytest.raises(AssertionError):
            build_zip({}, root_name='root')

    def test_empty_root_name_raises(self) -> None:
        """An empty root_name violates the precondition assertion."""
        with pytest.raises(AssertionError):
            build_zip({'a.txt': b'x'}, root_name='')
