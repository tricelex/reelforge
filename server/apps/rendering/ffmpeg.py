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
            f'ffprobe failed ({proc.returncode}): {stderr.decode()[:200]}',
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
            f'mux_scene failed ({proc.returncode}): {stderr.decode()[:300]}',
        )


async def concat_chapter(segment_paths: list[str], out_path: str) -> None:
    """Concatenate mezzanine segments using FFmpeg concat demuxer (stream copy).

    All segments must conform to mezzanine spec so -c copy is safe and fast.

    Raises:
        RuntimeError: If FFmpeg exits with non-zero return code.
    """
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False,
    ) as f:
        for seg in segment_paths:
            f.write(f"file '{seg}'\n")
        list_path = f.name

    cmd = [
        'ffmpeg',
        '-y',
        '-f',
        'concat',
        '-safe',
        '0',
        '-i',
        list_path,
        '-c',
        'copy',
        out_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    Path(list_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f'concat_chapter failed ({proc.returncode}): {stderr.decode()[:300]}',
        )


_LOUDNORM_I = -14.0
_LOUDNORM_TP = -1.0
_LOUDNORM_LRA = 11.0


async def loudnorm_pass1(path: str) -> dict[str, str]:
    """Measure EBU R128 loudness stats via FFmpeg loudnorm filter.

    Raises:
        RuntimeError: If FFmpeg exits non-zero.
        ValueError: If loudnorm JSON block not found in stderr.
    """
    cmd = [
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-af',
        (
            f'loudnorm=I={_LOUDNORM_I}:TP={_LOUDNORM_TP}:'
            f'LRA={_LOUDNORM_LRA}:print_format=json'
        ),
        '-f',
        'null',
        '-',
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode()
    start = stderr_text.rfind('{')
    end = stderr_text.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError(
            f'loudnorm JSON block not found in ffmpeg output: {stderr_text[:200]}',
        )
    return json.loads(stderr_text[start:end])  # type: ignore[no-any-return]


async def final_pass(
    chapter_paths: list[str],
    music_paths: list[str],
    music_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    out_path: str,
    watermark_opacity: float = 0.6,
) -> None:
    """Produce final video: concat chapters, loudnorm, watermark, subtitles, music.

    Steps:
    1. Concat chapter files to a temp intermediate (stream copy).
    2. Loudnorm pass 1 to measure integrated loudness.
    3. Build filter graph: optional watermark overlay, optional subtitle burn-in,
       optional music amix with per-track gain.
    4. Encode: libx264 CRF 18 slow, AAC 384k 48kHz, +faststart, -14 LUFS.

    Raises:
        RuntimeError: If any FFmpeg call exits non-zero.
    """
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        concat_tmp = f.name

    try:
        await concat_chapter(chapter_paths, concat_tmp)
        stats = await loudnorm_pass1(concat_tmp)

        inputs = ['-i', concat_tmp]
        for mp in music_paths:
            inputs += ['-i', mp]
        if watermark_path:
            inputs += ['-i', watermark_path]

        use_complex = bool(music_paths or watermark_path)
        wm_idx = 1 + len(music_paths)

        loudnorm_af = (
            f'loudnorm=I={_LOUDNORM_I}:TP={_LOUDNORM_TP}:LRA={_LOUDNORM_LRA}:'
            f"measured_I={stats.get('input_i', str(_LOUDNORM_I))}:"
            f"measured_TP={stats.get('input_tp', str(_LOUDNORM_TP))}:"
            f"measured_LRA={stats.get('input_lra', str(_LOUDNORM_LRA))}:"
            f"measured_thresh={stats.get('input_thresh', '-24.0')}:"
            f"offset={stats.get('target_offset', '0.0')}:"
            f'linear=true:print_format=summary'
        )

        if use_complex:
            filter_parts: list[str] = []

            if watermark_path:
                filter_parts.append(
                    f'[0:v][{wm_idx}:v]overlay=W-w-20:H-h-20:format=auto[vwm]',
                )
                v_out = '[vwm]'
            else:
                v_out = '[0:v]'

            if ass_path:
                filter_parts.append(f"{v_out}subtitles='{ass_path}'[vout]")
                v_out = '[vout]'

            if music_paths:
                for i, gain_db in enumerate(music_gains_db, start=1):
                    gain_linear = 10 ** (gain_db / 20.0)
                    filter_parts.append(
                        f'[{i}:a]volume={gain_linear:.4f}[m{i}]',
                    )
                music_refs = ''.join(
                    f'[m{i}]' for i in range(1, len(music_paths) + 1)
                )
                n = 1 + len(music_paths)
                filter_parts.append(
                    f'[0:a]{music_refs}amix=inputs={n}:duration=first,'
                    f'{loudnorm_af}[aout]',
                )
                a_out = '[aout]'
            else:
                filter_parts.append(f'[0:a]{loudnorm_af}[aout]')
                a_out = '[aout]'

            fc = ';'.join(filter_parts)
            vmap = v_out if v_out != '[0:v]' else '0:v'
            cmd = [
                'ffmpeg',
                '-y',
                *inputs,
                '-filter_complex',
                fc,
                '-map',
                vmap,
                '-map',
                a_out,
                '-c:v',
                'libx264',
                '-preset',
                'slow',
                '-crf',
                '18',
                '-pix_fmt',
                'yuv420p',
                '-r',
                '30',
                '-c:a',
                'aac',
                '-b:a',
                '384k',
                '-ar',
                '48000',
                '-ac',
                '2',
                '-movflags',
                '+faststart',
                out_path,
            ]
        else:
            vf_parts = []
            if ass_path:
                vf_parts.append(f"subtitles='{ass_path}'")
            vf = ','.join(vf_parts) if vf_parts else 'null'
            cmd = [
                'ffmpeg',
                '-y',
                *inputs,
                '-vf',
                vf,
                '-af',
                loudnorm_af,
                '-c:v',
                'libx264',
                '-preset',
                'slow',
                '-crf',
                '18',
                '-pix_fmt',
                'yuv420p',
                '-r',
                '30',
                '-c:a',
                'aac',
                '-b:a',
                '384k',
                '-ar',
                '48000',
                '-ac',
                '2',
                '-movflags',
                '+faststart',
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
                f'final_pass failed ({proc.returncode}): {stderr.decode()[:400]}',
            )
    finally:
        Path(concat_tmp).unlink(missing_ok=True)
