"""Async FFmpeg service functions for video assembly.

All functions use asyncio.create_subprocess_exec. Inputs and outputs are
plain types (bytes, Path, float) — no StageContext or Django ORM dependency.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any


async def async_ffprobe(path: str) -> dict[str, Any]:
    """Run ffprobe asynchronously and return parsed JSON.

    Raises:
        RuntimeError: If ffprobe exits with non-zero return code.
    """
    proc = await asyncio.create_subprocess_exec(
        'ffprobe',
        '-v',
        'quiet',
        '-print_format',
        'json',
        '-show_streams',
        '-show_format',
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f'ffprobe failed ({proc.returncode}): {stderr.decode()[:200]}'
        )
    return json.loads(stdout)  # type: ignore[no-any-return]
