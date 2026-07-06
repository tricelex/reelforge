"""Sync ffprobe helper for render stages (they run via subprocess, not asyncio)."""

import json
import subprocess  # noqa: S404


def sync_ffprobe_duration(path: str) -> float:
    """Return the media duration in seconds via ffprobe.

    Raises:
        RuntimeError: If ffprobe exits non-zero.
    """
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_format',
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f'ffprobe failed for {path}: {result.stderr}')
    data = json.loads(result.stdout)
    return float(data['format']['duration'])
