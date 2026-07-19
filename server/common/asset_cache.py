"""Checksum-verified local disk cache for immutable storage assets.

Downloads stream to a temporary file, verify SHA-256, then atomically rename
into the cache directory. Concurrent callers share one download via a
filesystem lock. Never loads entire objects into Python memory.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Final

# Writable without root; production sets ASSET_CACHE_DIR to a volume.
DEFAULT_CACHE_DIR: Final[str] = '/tmp/***REMOVED***/assets'  # noqa: S108
DEFAULT_CHUNK_SIZE: Final[int] = 1024 * 1024
DEFAULT_MAX_BYTES: Final[int] = 20 * 1024 * 1024 * 1024  # 20 GiB


class AssetCacheError(RuntimeError):
    """Raised when a cached asset cannot be materialized safely."""


def _resolve_cache_root(cache_dir: Path | str | None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    env_dir = os.environ.get('ASSET_CACHE_DIR')
    if env_dir:
        return Path(env_dir)
    return Path(DEFAULT_CACHE_DIR)


def _is_sha256_hex(value: str) -> bool:
    stripped = value.strip().lower()
    return len(stripped) == 64 and all(
        ch in '0123456789abcdef' for ch in stripped
    )


def _cache_key(checksum: str) -> str:
    """Return a filesystem-safe cache key for ``checksum``."""
    stripped = checksum.strip().lower()
    if _is_sha256_hex(stripped):
        return stripped
    # Legacy / fixture checksums: stable opaque key, still unique per value.
    return hashlib.sha256(checksum.encode('utf-8')).hexdigest()


def _cache_path(cache_dir: Path, checksum: str) -> Path:
    if not checksum.strip():
        msg = f'Invalid asset checksum for cache key: {checksum!r}'
        raise AssetCacheError(msg)
    return cache_dir / f'{_cache_key(checksum)}.bin'


def _verify_download(
    *,
    checksum: str,
    digest_hex: str,
    written: int,
    expected_size: int | None,
) -> None:
    if expected_size is not None and written != expected_size:
        msg = (
            f'Asset size mismatch for {checksum}: '
            f'expected {expected_size}, got {written}'
        )
        raise AssetCacheError(msg)
    # Only enforce content hash when the stored checksum is a real SHA-256.
    if _is_sha256_hex(checksum) and digest_hex != checksum.strip().lower():
        msg = f'Asset checksum mismatch for {checksum}'
        raise AssetCacheError(msg)


@contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive inter-process lock using ``fcntl`` (POSIX)."""
    import fcntl  # noqa: PLC0415

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stream_to_partial(
    *,
    open_stream: Callable[[], BinaryIO],
    partial: Path,
    chunk_size: int,
) -> tuple[str, int]:
    """Write stream bytes to ``partial``; return (sha256 hex, byte count)."""
    digest = hashlib.sha256()
    written = 0
    stream = open_stream()
    try:
        with partial.open('wb') as out:
            chunk = stream.read(chunk_size)
            while chunk:
                if len(chunk) > chunk_size:
                    msg = f'Chunk exceeded size bound: {len(chunk)}'
                    raise AssetCacheError(msg)
                digest.update(chunk)
                out.write(chunk)
                written += len(chunk)
                chunk = stream.read(chunk_size)
            out.flush()
            os.fsync(out.fileno())
    finally:
        stream.close()
    return digest.hexdigest(), written


def _touch_existing(target: Path) -> Path | None:
    if target.is_file() and target.stat().st_size > 0:
        os.utime(target, None)
        return target
    return None


def materialize_asset_file(
    *,
    checksum: str,
    open_stream: Callable[[], BinaryIO],
    cache_dir: Path | str | None = None,
    expected_size: int | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Path:
    """Return a local path for ``checksum``, downloading on cache miss.

    ``open_stream`` must return a binary file-like opened for reading (e.g.
    ``asset.file.open('rb')``). The stream is always closed.
    """
    if chunk_size <= 0:
        raise ValueError('chunk_size must be positive')
    root = _resolve_cache_root(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = _cache_path(root, checksum)
    hit = _touch_existing(target)
    if hit is not None:
        return hit

    lock_path = root / f'{_cache_key(checksum)}.lock'
    with _file_lock(lock_path):
        hit = _touch_existing(target)
        if hit is not None:
            return hit
        partial = root / f'{_cache_key(checksum)}.{os.getpid()}.partial'
        try:
            digest_hex, written = _stream_to_partial(
                open_stream=open_stream,
                partial=partial,
                chunk_size=chunk_size,
            )
            _verify_download(
                checksum=checksum,
                digest_hex=digest_hex,
                written=written,
                expected_size=expected_size,
            )
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        finally:
            lock_path.unlink(missing_ok=True)
    return target


def materialize_to_path(
    *,
    checksum: str,
    open_stream: Callable[[], BinaryIO],
    destination: Path,
    cache_dir: Path | str | None = None,
    expected_size: int | None = None,
) -> Path:
    """Materialize into ``destination`` via hard-link, falling back to copy."""
    import shutil  # noqa: PLC0415

    cached = materialize_asset_file(
        checksum=checksum,
        open_stream=open_stream,
        cache_dir=cache_dir,
        expected_size=expected_size,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(cached, destination)
    except OSError:
        shutil.copy2(cached, destination)
    return destination


def cleanup_asset_cache(
    *,
    cache_dir: Path | str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> int:
    """Delete least-recently-used ``.bin`` files until under ``max_bytes``.

    Returns the number of files removed.
    """
    if max_bytes < 0:
        raise ValueError('max_bytes must be non-negative')
    root = _resolve_cache_root(cache_dir)
    if not root.is_dir():
        return 0
    files = [path for path in root.glob('*.bin') if path.is_file()]
    files.sort(key=lambda path: path.stat().st_atime)
    total = sum(path.stat().st_size for path in files)
    removed = 0
    for path in files:
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size
        removed += 1
    _cleanup_stale_locks(root)
    return removed


def _cleanup_stale_locks(root: Path) -> None:
    now = time.time()
    for lock in root.glob('*.lock'):
        try:
            if now - lock.stat().st_mtime > 86_400:
                lock.unlink(missing_ok=True)
        except OSError:
            continue
