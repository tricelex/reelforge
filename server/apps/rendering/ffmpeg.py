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


_DRIFT_THRESHOLD = 0.05  # 5% — below: setpts/atempo; above: hold last frame


async def mux_scene(
    video_path: str,
    audio_path: str,
    start_s: float,
    end_s: float,
    out_path: str,
) -> None:
    """Trim audio window and fit video to narration duration, then mux.

    Probes motion video duration. If drift <= 5% uses setpts PTS scaling;
    otherwise pads video with tpad (hold last frame). Always re-encodes to
    mezzanine spec: libx264 CRF 16, yuv420p, 30fps, AAC 48kHz stereo.

    Raises:
        RuntimeError: If FFmpeg exits with non-zero return code.
    """
    narration_dur = end_s - start_s
    probe = await async_ffprobe(video_path)
    motion_dur = float(probe.get('format', {}).get('duration', narration_dur))
    if motion_dur <= 0:
        motion_dur = narration_dur

    drift = abs(motion_dur - narration_dur) / max(motion_dur, narration_dur)

    if drift <= _DRIFT_THRESHOLD:
        pts_factor = narration_dur / motion_dur if motion_dur > 0 else 1.0
        atempo = max(0.5, min(2.0, pts_factor))
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            video_path,
            '-ss',
            f'{start_s:.3f}',
            '-to',
            f'{end_s:.3f}',
            '-i',
            audio_path,
            '-vf',
            f'setpts={pts_factor:.6f}*PTS',
            '-af',
            (
                f'atrim=start={start_s:.3f}:end={end_s:.3f},'
                f'asetpts=PTS-STARTPTS,atempo={atempo:.6f}'
            ),
            '-c:v',
            'libx264',
            '-crf',
            '16',
            '-pix_fmt',
            'yuv420p',
            '-r',
            '30',
            '-c:a',
            'aac',
            '-ar',
            '48000',
            '-ac',
            '2',
            '-shortest',
            out_path,
        ]
    else:
        pad_s = max(0.0, narration_dur - motion_dur)
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            video_path,
            '-ss',
            f'{start_s:.3f}',
            '-to',
            f'{end_s:.3f}',
            '-i',
            audio_path,
            '-vf',
            f'tpad=stop_mode=clone:stop_duration={pad_s:.3f}',
            '-af',
            (
                f'atrim=start={start_s:.3f}:end={end_s:.3f},'
                f'asetpts=PTS-STARTPTS'
            ),
            '-c:v',
            'libx264',
            '-crf',
            '16',
            '-pix_fmt',
            'yuv420p',
            '-r',
            '30',
            '-c:a',
            'aac',
            '-ar',
            '48000',
            '-ac',
            '2',
            '-t',
            f'{narration_dur:.3f}',
            out_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f'mux_scene failed ({proc.returncode}): {stderr.decode()[:300]}'
        )
