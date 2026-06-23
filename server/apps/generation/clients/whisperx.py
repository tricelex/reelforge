"""WhisperX forced alignment via subprocess (runs on GPU queue workers)."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any


async def align(
    audio_path: str,
    transcript_text: str,
    language: str = 'en',
    device: str = 'cpu',
    compute_type: str = 'int8',
) -> dict[str, Any]:
    """Run WhisperX alignment. Returns word-level timestamps as a dict."""
    out_dir = tempfile.mkdtemp()
    cmd = [
        'python',
        '-m',
        'whisperx',
        audio_path,
        '--language',
        language,
        '--device',
        device,
        '--compute_type',
        compute_type,
        '--output_format',
        'json',
        '--output_dir',
        out_dir,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f'WhisperX failed: {stderr.decode()[:500]}')

    out_file = Path(out_dir) / (Path(audio_path).stem + '.json')
    content = await asyncio.to_thread(out_file.read_text, encoding='utf-8')
    return json.loads(content)  # type: ignore[no-any-return]
