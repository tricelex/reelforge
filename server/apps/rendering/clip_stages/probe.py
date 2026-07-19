"""Sync ffprobe helpers for render stages (subprocess, not asyncio)."""

import json
import subprocess  # noqa: S404
from typing import Any


def sync_ffprobe_duration(path: str) -> float:
    """Return the media duration in seconds via ffprobe.

    Raises:
        RuntimeError: If ffprobe exits non-zero.
    """
    data = _sync_ffprobe_json(path, show_streams=False)
    return float(data['format']['duration'])


def sync_ffprobe_dimensions(path: str) -> tuple[int | None, int | None]:
    """Return video stream (width, height) via ffprobe, or (None, None)."""
    try:
        data = _sync_ffprobe_json(path, show_streams=True)
    except RuntimeError:
        return None, None
    for stream in data.get('streams', []):
        if stream.get('codec_type') != 'video':
            continue
        width = stream.get('width')
        height = stream.get('height')
        if isinstance(width, int) and isinstance(height, int):
            return width, height
    return None, None


def _sync_ffprobe_json(path: str, *, show_streams: bool) -> dict[str, Any]:
    """Run ffprobe and return parsed JSON.

    Raises:
        RuntimeError: If ffprobe exits non-zero.
    """
    cmd = [
        'ffprobe',
        '-v',
        'quiet',
        '-print_format',
        'json',
        '-show_format',
    ]
    if show_streams:
        cmd.append('-show_streams')
    cmd.append(path)
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f'ffprobe failed for {path}: {result.stderr}')
    return json.loads(result.stdout)  # type: ignore[no-any-return]
