"""Tests for checksum-verified local asset materialization."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.common.asset_cache import (
    AssetCacheError,
    cleanup_asset_cache,
    materialize_asset_file,
    materialize_to_path,
)


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_materialize_writes_and_reuses_cached_file(
    tmp_path: Path,
) -> None:
    content = b'video-bytes-123'
    checksum = _checksum(content)
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])

    first = materialize_asset_file(
        checksum=checksum,
        open_stream=lambda: source,
        cache_dir=tmp_path,
        expected_size=len(content),
    )
    assert first.read_bytes() == content
    assert source.read.call_count >= 1

    source2 = MagicMock()
    source2.read = MagicMock(side_effect=AssertionError('should not download'))
    second = materialize_asset_file(
        checksum=checksum,
        open_stream=lambda: source2,
        cache_dir=tmp_path,
        expected_size=len(content),
    )
    assert second == first
    source2.read.assert_not_called()


def test_materialize_rejects_checksum_mismatch(tmp_path: Path) -> None:
    content = b'wrong-bytes'
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])
    real = _checksum(b'expected')

    with pytest.raises(AssetCacheError, match='checksum'):
        materialize_asset_file(
            checksum=real,
            open_stream=lambda: source,
            cache_dir=tmp_path,
        )
    assert list(tmp_path.glob('*.partial')) == []
    assert list(tmp_path.glob('*.bin')) == []


def test_materialize_allows_legacy_non_sha_checksum(tmp_path: Path) -> None:
    content = b'legacy-video'
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])
    path = materialize_asset_file(
        checksum='abc',
        open_stream=lambda: source,
        cache_dir=tmp_path,
    )
    assert path.read_bytes() == content


def test_materialize_rejects_empty_checksum(tmp_path: Path) -> None:
    with pytest.raises(AssetCacheError, match='Invalid'):
        materialize_asset_file(
            checksum='   ',
            open_stream=lambda: MagicMock(),
            cache_dir=tmp_path,
        )


def test_materialize_rejects_size_mismatch(tmp_path: Path) -> None:
    content = b'abc'
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])

    with pytest.raises(AssetCacheError, match='size'):
        materialize_asset_file(
            checksum=_checksum(content),
            open_stream=lambda: source,
            cache_dir=tmp_path,
            expected_size=99,
        )


def test_materialize_rejects_bad_chunk_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='chunk_size'):
        materialize_asset_file(
            checksum=_checksum(b'x'),
            open_stream=lambda: MagicMock(),
            cache_dir=tmp_path,
            chunk_size=0,
        )


def test_materialize_to_path_copies_or_links(tmp_path: Path) -> None:
    content = b'frame-source'
    checksum = _checksum(content)
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])
    dest = tmp_path / 'out' / 'source.mp4'

    materialize_to_path(
        checksum=checksum,
        open_stream=lambda: source,
        destination=dest,
        cache_dir=tmp_path / 'cache',
    )
    assert dest.read_bytes() == content


def test_cleanup_respects_byte_budget(tmp_path: Path) -> None:
    older = tmp_path / 'aaa.bin'
    newer = tmp_path / 'bbb.bin'
    older.write_bytes(b'12345')
    newer.write_bytes(b'67890')
    import os
    import time

    past = time.time() - 100
    os.utime(older, (past, past))

    removed = cleanup_asset_cache(cache_dir=tmp_path, max_bytes=6)
    assert removed >= 1
    assert not older.exists()
    assert newer.exists()


def test_cleanup_noop_when_missing_or_negative(tmp_path: Path) -> None:
    assert cleanup_asset_cache(cache_dir=tmp_path / 'missing') == 0
    with pytest.raises(ValueError, match='max_bytes'):
        cleanup_asset_cache(cache_dir=tmp_path, max_bytes=-1)


def test_resolve_cache_root_uses_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.common.asset_cache import _resolve_cache_root

    monkeypatch.setenv('ASSET_CACHE_DIR', str(tmp_path / 'env-cache'))
    assert _resolve_cache_root(None) == tmp_path / 'env-cache'


def test_stream_rejects_oversized_chunk(tmp_path: Path) -> None:
    source = MagicMock()
    source.read = MagicMock(return_value=b'x' * 10)

    with pytest.raises(AssetCacheError, match='Chunk exceeded'):
        materialize_asset_file(
            checksum='legacy-key',
            open_stream=lambda: source,
            cache_dir=tmp_path,
            chunk_size=4,
        )


def test_materialize_to_path_replaces_existing(tmp_path: Path) -> None:
    content = b'replace-me'
    checksum = _checksum(content)
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])
    dest = tmp_path / 'out.mp4'
    dest.write_bytes(b'old')

    materialize_to_path(
        checksum=checksum,
        open_stream=lambda: source,
        destination=dest,
        cache_dir=tmp_path / 'cache',
    )
    assert dest.read_bytes() == content


def test_cleanup_removes_stale_locks(tmp_path: Path) -> None:
    import os
    import time

    kept = tmp_path / 'keep.bin'
    kept.write_bytes(b'ok')
    lock = tmp_path / 'stale.lock'
    lock.write_text('x', encoding='utf-8')
    past = time.time() - 200_000
    os.utime(lock, (past, past))

    removed = cleanup_asset_cache(cache_dir=tmp_path, max_bytes=10_000)
    assert removed == 0
    assert kept.exists()
    assert not lock.exists()


def test_resolve_default_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.common.asset_cache import DEFAULT_CACHE_DIR, _resolve_cache_root

    monkeypatch.delenv('ASSET_CACHE_DIR', raising=False)
    assert _resolve_cache_root(None) == Path(DEFAULT_CACHE_DIR)


def test_materialize_hit_after_lock_race(tmp_path: Path) -> None:
    from contextlib import contextmanager
    from unittest.mock import patch

    content = b'raced-in'
    checksum = _checksum(content)
    target = tmp_path / f'{checksum}.bin'

    @contextmanager
    def _fake_lock(_lock_path: Path):  # noqa: ANN202
        target.write_bytes(content)
        yield

    source = MagicMock()
    source.read = MagicMock(side_effect=AssertionError('should not download'))
    with patch('server.common.asset_cache._file_lock', _fake_lock):
        path = materialize_asset_file(
            checksum=checksum,
            open_stream=lambda: source,
            cache_dir=tmp_path,
        )
    assert path == target
    source.read.assert_not_called()


def test_materialize_to_path_falls_back_to_copy(tmp_path: Path) -> None:
    from unittest.mock import patch

    content = b'copy-fallback'
    checksum = _checksum(content)
    source = MagicMock()
    source.read = MagicMock(side_effect=[content, b''])
    dest = tmp_path / 'dest.mp4'

    with patch('os.link', side_effect=OSError('cross-device')):
        materialize_to_path(
            checksum=checksum,
            open_stream=lambda: source,
            destination=dest,
            cache_dir=tmp_path / 'cache',
        )
    assert dest.read_bytes() == content


def test_cleanup_keeps_young_locks_and_handles_stat_errors(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    young = tmp_path / 'young.lock'
    young.write_text('y', encoding='utf-8')
    broken = tmp_path / 'broken.lock'
    broken.write_text('b', encoding='utf-8')

    real_stat = Path.stat

    def _stat(self: Path, *args: object, **kwargs: object):  # noqa: ANN202
        if self.name == 'broken.lock':
            raise OSError('gone')
        return real_stat(self, *args, **kwargs)

    with patch.object(Path, 'stat', _stat):
        removed = cleanup_asset_cache(cache_dir=tmp_path, max_bytes=10_000)
    assert removed == 0
    assert young.exists()
