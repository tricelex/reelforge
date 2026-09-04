"""Async FFmpeg service functions for video assembly.

All functions use asyncio.create_subprocess_exec. Inputs and outputs are
plain types (bytes, Path, float) — no StageContext or Django ORM dependency.
"""

import asyncio
import json
import tempfile
from itertools import starmap
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_MEZZANINE_VF = (
    'scale=1920:1080:force_original_aspect_ratio=decrease,'
    'pad=1920:1080:(ow-iw)/2:(oh-ih)/2'
)
_FFMPEG_ERROR_MARKERS = (
    'error',
    'invalid',
    'no such file',
    'matches no streams',
    'does not contain',
    'conversion failed',
)
_XFADE_TRANSITION_NAMES: dict[str, str] = {
    'cross_dissolve': 'fade',
    'fade': 'fade',
    'fade_black': 'fadeblack',
    'fade_white': 'fadewhite',
    'slide_left': 'slideleft',
    'slide_right': 'slideright',
    'slide_up': 'slideup',
    'slide_down': 'slidedown',
    'wipe_left': 'wipeleft',
    'wipe_right': 'wiperight',
    'zoom_in': 'zoomin',
}
_DEFAULT_XFADE_NAME = 'fade'


def _extract_ffmpeg_error(stderr: str, limit: int = 500) -> str:
    """Prefer the actionable FFmpeg error line over the version banner."""
    text = stderr.strip()
    if not text:
        return '(no stderr)'
    lines = text.splitlines()
    for line in lines:
        lower = line.lower()
        if any(marker in lower for marker in _FFMPEG_ERROR_MARKERS):
            return line.strip()[:limit]
    return text[-limit:]


_KEN_BURNS_PRESETS = [
    "zoompan=z='zoom+0.008':d=150:s=1920x1080",
    "zoompan=z='1.12-0.008*on':d=150:s=1920x1080",
    "zoompan=x='iw/2-(iw/zoom/2)+on*8':z=1.08:d=150:s=1920x1080",
    "zoompan=x='iw-(iw/zoom/2)-on*8':z=1.08:d=150:s=1920x1080",
]


async def ken_burns(
    image_bytes: bytes,
    duration_s: float,
    preset_idx: int = 0,
) -> bytes:
    """Apply a Ken Burns zoom/pan to image bytes and return mp4 bytes."""
    if not image_bytes:
        raise ValueError('image_bytes must be non-empty')
    if duration_s <= 0:
        raise ValueError(f'duration_s must be > 0, got {duration_s}')

    with (
        tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as img_f,
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as vid_f,
    ):
        img_path = img_f.name
        vid_path = vid_f.name
    try:
        await asyncio.to_thread(Path(img_path).write_bytes, image_bytes)

        frames = int(duration_s * 30)
        vf = _KEN_BURNS_PRESETS[preset_idx % len(_KEN_BURNS_PRESETS)].replace(
            'd=150',
            f'd={frames}',
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-loop',
            '1',
            '-i',
            img_path,
            '-vf',
            vf,
            '-t',
            str(duration_s),
            '-r',
            '30',
            '-c:v',
            'libx264',
            '-crf',
            '16',
            '-pix_fmt',
            'yuv420p',
            '-an',
            vid_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f'FFmpeg Ken Burns failed: {stderr.decode()[:300]}',
            )

        video_bytes = await asyncio.to_thread(Path(vid_path).read_bytes)
        if not video_bytes:
            raise RuntimeError('Ken Burns produced empty video')
        return video_bytes
    finally:
        await asyncio.to_thread(Path(img_path).unlink, missing_ok=True)
        await asyncio.to_thread(Path(vid_path).unlink, missing_ok=True)


async def normalize_clip(
    video_bytes: bytes,
    duration_s: float,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> tuple[bytes, str]:
    """Fit a sourced clip to a scene: trim or loop, scale, strip audio.

    Trimming always takes the window from the start of the clip so a shard
    rerun produces an identical segment. Returns (mp4_bytes, method) where
    method is 'clip_trim' or 'clip_loop'.
    """
    if not video_bytes:
        raise ValueError('video_bytes must be non-empty')
    if duration_s <= 0:
        raise ValueError(f'duration_s must be > 0, got {duration_s}')

    with (
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as src_f,
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as out_f,
    ):
        src_path = src_f.name
        out_path = out_f.name
    try:
        await asyncio.to_thread(Path(src_path).write_bytes, video_bytes)
        probe = await async_ffprobe(src_path)
        source_duration = float(
            probe.get('format', {}).get('duration', 0.0) or 0.0,
        )
        needs_loop = source_duration < duration_s
        method = 'clip_loop' if needs_loop else 'clip_trim'

        vf = (
            f'scale={width}:{height}:force_original_aspect_ratio=increase,'
            f'crop={width}:{height},fps={fps}'
        )
        cmd = ['ffmpeg', '-y']
        if needs_loop:
            cmd += ['-stream_loop', '-1']
        cmd += [
            '-i',
            src_path,
            '-t',
            str(duration_s),
            '-vf',
            vf,
            '-c:v',
            'libx264',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
            '-an',
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
                f'FFmpeg normalize_clip failed: {stderr.decode()[:300]}',
            )

        out_bytes = await asyncio.to_thread(Path(out_path).read_bytes)
        if not out_bytes:
            raise RuntimeError('normalize_clip produced empty video')
        return out_bytes, method
    finally:
        await asyncio.to_thread(Path(src_path).unlink, missing_ok=True)
        await asyncio.to_thread(Path(out_path).unlink, missing_ok=True)


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
            f'ffprobe failed ({proc.returncode}): '
            f'{_extract_ffmpeg_error(stderr.decode())}',
        )
    return json.loads(stdout)  # type: ignore[no-any-return]


_DRIFT_THRESHOLD = 0.05  # 5% — below: setpts/atempo; above: hold last frame


def _has_audio_stream(probe: dict[str, Any]) -> bool:
    """Return True when ffprobe JSON includes at least one audio stream."""
    streams = probe.get('streams', [])
    return any(s.get('codec_type') == 'audio' for s in streams)


def _mezzanine_encode_tail(narration_dur: float, out_path: str) -> list[str]:
    """Shared mezzanine encode flags with explicit A/V stream mapping."""
    return [
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
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


def _build_mux_scene_cmd(
    *,
    video_path: str,
    audio_path: str,
    start_s: float,
    end_s: float,
    narration_dur: float,
    motion_dur: float,
    out_path: str,
) -> list[str]:
    """Build ffmpeg argv for fitting motion video to narration duration.

    The chapter audio is trimmed once, by the sample-accurate atrim filter.
    Do NOT add -ss/-to input seeking on the audio: input seeking resets
    timestamps to zero, which makes the absolute-time atrim window empty
    for any scene that starts later in the chapter (video-only output).
    """
    drift = abs(motion_dur - narration_dur) / max(motion_dur, narration_dur)
    inputs = ['ffmpeg', '-y', '-i', video_path, '-i', audio_path]
    if drift <= _DRIFT_THRESHOLD:
        pts_factor = narration_dur / motion_dur if motion_dur > 0 else 1.0
        atempo = max(0.5, min(2.0, pts_factor))
        return [
            *inputs,
            '-vf',
            f'setpts={pts_factor:.6f}*PTS,{_MEZZANINE_VF}',
            '-af',
            (
                f'atrim=start={start_s:.3f}:end={end_s:.3f},'
                f'asetpts=PTS-STARTPTS,atempo={atempo:.6f}'
            ),
            *_mezzanine_encode_tail(narration_dur, out_path),
        ]
    pad_s = max(0.0, narration_dur - motion_dur)
    return [
        *inputs,
        '-vf',
        f'tpad=stop_mode=clone:stop_duration={pad_s:.3f},{_MEZZANINE_VF}',
        '-af',
        f'atrim=start={start_s:.3f}:end={end_s:.3f},asetpts=PTS-STARTPTS',
        *_mezzanine_encode_tail(narration_dur, out_path),
    ]


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
    mezzanine spec: 1920x1080, libx264 CRF 16, yuv420p, 30fps, AAC 48kHz
    stereo.

    Raises:
        ValueError: If ``end_s <= start_s``.
        RuntimeError: If FFmpeg exits non-zero or output lacks audio.
    """
    narration_dur = end_s - start_s
    if narration_dur <= 0:
        raise ValueError(
            f'mux_scene requires end_s > start_s '
            f'(got start_s={start_s}, end_s={end_s})',
        )
    probe = await async_ffprobe(video_path)
    motion_dur = float(probe.get('format', {}).get('duration', narration_dur))
    if motion_dur <= 0:
        motion_dur = narration_dur

    cmd = _build_mux_scene_cmd(
        video_path=video_path,
        audio_path=audio_path,
        start_s=start_s,
        end_s=end_s,
        narration_dur=narration_dur,
        motion_dur=motion_dur,
        out_path=out_path,
    )
    await _run_ffmpeg_cmd(cmd, label='mux_scene')
    out_probe = await async_ffprobe(out_path)
    if not _has_audio_stream(out_probe):
        raise RuntimeError(
            f'mux_scene produced video-only output for {out_path}',
        )


async def concat_chapter(segment_paths: list[str], out_path: str) -> None:
    """Concatenate mezzanine segments using FFmpeg concat demuxer (stream copy).

    All segments must conform to mezzanine spec so -c copy is safe and fast.

    Raises:
        ValueError: If ``segment_paths`` is empty.
        RuntimeError: If FFmpeg exits with non-zero return code.
    """
    if not segment_paths:
        raise ValueError('concat_chapter requires at least one segment path')

    with tempfile.NamedTemporaryFile(
        encoding='utf-8',
        mode='w',
        suffix='.txt',
        delete=False,
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
    await asyncio.to_thread(Path(list_path).unlink, missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            'concat_chapter failed '
            f'({proc.returncode}): {_extract_ffmpeg_error(stderr.decode())}',
        )


_MIN_TRANSITION_SEGMENTS = 2


async def _probe_duration(path: str) -> float:
    """Return the container duration in seconds for a media file."""
    probe = await async_ffprobe(path)
    return float(probe.get('format', {}).get('duration', 0.0))


def _xfade_name(transition: str) -> str:
    """Map assembly transition style to an FFmpeg xfade transition name."""
    return _XFADE_TRANSITION_NAMES.get(transition, _DEFAULT_XFADE_NAME)


def _build_xfade_filter(
    durations: list[float],
    transition_duration_s: float,
    transition: str = 'fade',
) -> tuple[str, str, str]:
    """Cascading xfade/acrossfade filter_complex chain across N inputs.

    Returns (filter_complex, video_out_label, audio_out_label).
    """
    xfade = _xfade_name(transition)
    parts: list[str] = []
    cum = durations[0]
    v_prev = '[0:v]'
    a_prev = '[0:a]'
    for i in range(1, len(durations)):
        offset = max(cum - transition_duration_s, 0.0)
        v_out = f'[v{i}]'
        a_out = f'[a{i}]'
        v_str = (
            f'{v_prev}[{i}:v]xfade=transition={xfade}:'
            f'duration={transition_duration_s}:offset={offset:.3f}{v_out}'
        )
        a_str = f'{a_prev}[{i}:a]acrossfade=d={transition_duration_s}{a_out}'
        parts.extend((v_str, a_str))
        v_prev, a_prev = v_out, a_out
        cum += durations[i] - transition_duration_s
    return ';'.join(parts), v_prev, a_prev


async def _ensure_segment_has_audio(path: str, duration_s: float) -> str:
    """Re-mux a video-only segment with silent stereo AAC; return temp path."""
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        out_path = f.name
    dur = max(duration_s, 0.1)
    cmd = [
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-f',
        'lavfi',
        '-i',
        'anullsrc=channel_layout=stereo:sample_rate=48000',
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-c:v',
        'copy',
        '-c:a',
        'aac',
        '-ar',
        '48000',
        '-ac',
        '2',
        '-t',
        f'{dur:.3f}',
        out_path,
    ]
    await _run_ffmpeg_cmd(cmd, label='ensure_segment_audio')
    logger.info(
        'ffmpeg_segment_audio_normalized',
        source=path,
        normalized=out_path,
        duration_s=dur,
    )
    return out_path


async def _normalize_segments_for_xfade(
    segment_paths: list[str],
) -> tuple[list[str], list[float], list[str]]:
    """Probe segments; inject silent audio where missing.

    Returns (normalized_paths, durations, temp_paths_to_cleanup).
    """
    normalized: list[str] = []
    durations: list[float] = []
    temps: list[str] = []
    for path in segment_paths:
        probe = await async_ffprobe(path)
        duration = float(probe.get('format', {}).get('duration', 0.0))
        durations.append(duration)
        if _has_audio_stream(probe):
            normalized.append(path)
            continue
        fixed = await _ensure_segment_has_audio(path, duration)
        temps.append(fixed)
        normalized.append(fixed)
    return normalized, durations, temps


# Cap on simultaneous inputs per xfade filter_complex call. A cascading
# chain across every scene in a chapter opens one decoder per scene in a
# single FFmpeg process — for long-form chapters (dozens of scenes) that
# graph's memory scales unboundedly and can get the process OOM-killed.
# Batching bounds each call to a small, constant input count regardless of
# chapter size.
_MAX_XFADE_INPUTS = 6

# Concurrent xfade batches within one round. Each batch is a bounded,
# independent FFmpeg process (its own inputs, its own out_path), so running
# a few at once is as safe as _SCENE_MUX_CONCURRENCY is for scene muxing.
# Merging batches strictly one at a time turned long chapters (many batches
# per round) into a fully serial chain of full re-encodes - no single call
# was slow, but the chain was long enough to blow the assembly stage's
# overall timeout. Kept low so concurrent batches don't recreate the same
# memory pressure batching was meant to bound in the first place.
_XFADE_BATCH_CONCURRENCY = 2


def _temp_mp4_path() -> str:
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        return f.name


async def _xfade_batch(
    paths: list[str],
    durations: list[float],
    transition: str,
    transition_duration_s: float,
    out_path: str,
) -> None:
    """Cross-fade 2+ inputs (bounded by _MAX_XFADE_INPUTS) into one file."""
    filter_complex, v_out, a_out = _build_xfade_filter(
        durations,
        transition_duration_s,
        transition=transition,
    )
    inputs: list[str] = []
    for p in paths:
        inputs += ['-i', p]

    cmd = [
        'ffmpeg',
        '-y',
        *inputs,
        '-filter_complex',
        filter_complex,
        '-map',
        v_out,
        '-map',
        a_out,
        *_final_encode_args(out_path),
    ]
    await _run_ffmpeg_cmd(cmd, label='concat_chapter_with_transition')


async def _xfade_round(
    paths: list[str],
    durs: list[float],
    *,
    transition: str,
    transition_duration_s: float,
    out_path: str,
    is_final_round: bool,
    temps: list[str],
) -> tuple[list[str], list[float]]:
    """Merge one batching round; returns the next round's (paths, durs)."""
    chunks = [
        paths[i : i + _MAX_XFADE_INPUTS]
        for i in range(0, len(paths), _MAX_XFADE_INPUTS)
    ]
    dur_chunks = [
        durs[i : i + _MAX_XFADE_INPUTS]
        for i in range(0, len(durs), _MAX_XFADE_INPUTS)
    ]
    semaphore = asyncio.Semaphore(_XFADE_BATCH_CONCURRENCY)

    async def _merge_chunk(
        chunk: list[str],
        chunk_durs: list[float],
    ) -> tuple[str, float]:
        if len(chunk) == 1:
            return chunk[0], chunk_durs[0]
        dest = out_path if is_final_round else _temp_mp4_path()
        if not is_final_round:
            temps.append(dest)
        async with semaphore:
            await _xfade_batch(
                chunk,
                chunk_durs,
                transition,
                transition_duration_s,
                dest,
            )
        return dest, await _probe_duration(dest)

    merged = await asyncio.gather(
        *starmap(_merge_chunk, zip(chunks, dur_chunks, strict=True)),
    )
    merged_paths = [path for path, _ in merged]
    merged_durs = [dur for _, dur in merged]
    return merged_paths, merged_durs


async def concat_chapter_with_transition(
    segment_paths: list[str],
    transition: str,
    transition_duration_s: float,
    out_path: str,
) -> None:
    """Concatenate chapter files with a named transition between each pair.

    transition='hard_cut' delegates to the existing stream-copy concat_chapter
    (fast path, no re-encode). Any other transition name re-encodes using
    xfade/acrossfade, batching inputs in groups of _MAX_XFADE_INPUTS and
    cascading the batch outputs so no single FFmpeg call ever opens more
    than a bounded number of decoders at once.

    Raises:
        RuntimeError: If FFmpeg exits with non-zero return code.
    """
    if (
        transition == 'hard_cut'
        or len(segment_paths) < _MIN_TRANSITION_SEGMENTS
    ):
        await concat_chapter(segment_paths, out_path)
        return

    temps: list[str] = []
    try:
        normalized, durations, norm_temps = await _normalize_segments_for_xfade(
            segment_paths,
        )
        temps.extend(norm_temps)

        paths, durs = normalized, durations
        while len(paths) > 1:
            is_final_round = len(paths) <= _MAX_XFADE_INPUTS
            paths, durs = await _xfade_round(
                paths,
                durs,
                transition=transition,
                transition_duration_s=transition_duration_s,
                out_path=out_path,
                is_final_round=is_final_round,
                temps=temps,
            )
    finally:
        for tmp in temps:
            await asyncio.to_thread(Path(tmp).unlink, missing_ok=True)


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
            'loudnorm JSON block not found in ffmpeg output: '
            f'{stderr_text[:200]}',
        )
    return json.loads(stderr_text[start:end])  # type: ignore[no-any-return]


def _loudnorm_audio_filter(stats: dict[str, str]) -> str:
    """Build loudnorm filter string from pass-1 measurement stats."""
    return (
        f'loudnorm=I={_LOUDNORM_I}:TP={_LOUDNORM_TP}:LRA={_LOUDNORM_LRA}:'
        f'measured_I={stats.get("input_i", str(_LOUDNORM_I))}:'
        f'measured_TP={stats.get("input_tp", str(_LOUDNORM_TP))}:'
        f'measured_LRA={stats.get("input_lra", str(_LOUDNORM_LRA))}:'
        f'measured_thresh={stats.get("input_thresh", "-24.0")}:'
        f'offset={stats.get("target_offset", "0.0")}:'
        f'linear=true:print_format=summary'
    )


def _final_encode_args(out_path: str) -> list[str]:
    """Shared libx264/AAC encode flags for the final pass."""
    return [
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


def _build_complex_filter(
    *,
    music_paths: list[str],
    music_gains_db: list[float],
    sfx_paths: list[str],
    sfx_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    wm_idx: int,
    loudnorm_af: str,
    duration_s: float = 0.0,
) -> tuple[str, str, str]:
    """Return (filter_complex, video_map, audio_map) for final_pass.

    Music beds are looped/trimmed to ``duration_s`` so short library tracks
    cover the full VO timeline. SFX are left unlooped.
    """
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

    music_count = len(music_paths)
    extra_paths = music_paths + sfx_paths
    extra_gains = music_gains_db + sfx_gains_db
    if extra_paths:
        for i, gain_db in enumerate(extra_gains, start=1):
            gain_linear = 10 ** (gain_db / 20.0)
            is_music = i <= music_count
            if is_music and duration_s > 0:
                filter_parts.append(
                    f'[{i}:a]aloop=loop=-1:size=2e+09,'
                    f'atrim=0:{duration_s:.3f},'
                    f'asetpts=PTS-STARTPTS,'
                    f'volume={gain_linear:.4f}[m{i}]',
                )
            else:
                filter_parts.append(
                    f'[{i}:a]volume={gain_linear:.4f}[m{i}]',
                )
        music_refs = ''.join(f'[m{i}]' for i in range(1, len(extra_paths) + 1))
        n = 1 + len(extra_paths)
        filter_parts.append(
            f'[0:a]{music_refs}amix=inputs={n}:duration=first,'
            f'{loudnorm_af}[aout]',
        )
        a_out = '[aout]'
    else:
        filter_parts.append(f'[0:a]{loudnorm_af}[aout]')
        a_out = '[aout]'

    vmap = v_out if v_out != '[0:v]' else '0:v'
    return ';'.join(filter_parts), vmap, a_out


def _build_final_pass_cmd(
    *,
    inputs: list[str],
    music_paths: list[str],
    music_gains_db: list[float],
    sfx_paths: list[str],
    sfx_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    loudnorm_af: str,
    out_path: str,
    duration_s: float = 0.0,
) -> list[str]:
    """Assemble the ffmpeg argv for the final encode pass."""
    use_complex = bool(music_paths or sfx_paths or watermark_path)
    wm_idx = 1 + len(music_paths) + len(sfx_paths)

    if use_complex:
        fc, vmap, a_out = _build_complex_filter(
            music_paths=music_paths,
            music_gains_db=music_gains_db,
            sfx_paths=sfx_paths,
            sfx_gains_db=sfx_gains_db,
            ass_path=ass_path,
            watermark_path=watermark_path,
            wm_idx=wm_idx,
            loudnorm_af=loudnorm_af,
            duration_s=duration_s,
        )
        return [
            'ffmpeg',
            '-y',
            *inputs,
            '-filter_complex',
            fc,
            '-map',
            vmap,
            '-map',
            a_out,
            *_final_encode_args(out_path),
        ]

    vf_parts = []
    if ass_path:
        vf_parts.append(f"subtitles='{ass_path}'")
    vf = ','.join(vf_parts) if vf_parts else 'null'
    return [
        'ffmpeg',
        '-y',
        *inputs,
        '-vf',
        vf,
        '-af',
        loudnorm_af,
        *_final_encode_args(out_path),
    ]


async def _run_ffmpeg_cmd(
    cmd: list[str],
    *,
    label: str = 'final_pass',
) -> None:
    """Run ffmpeg and raise RuntimeError on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f'{label} failed ({proc.returncode}): '
            f'{_extract_ffmpeg_error(stderr.decode())}',
        )


async def final_pass(
    chapter_paths: list[str],
    music_paths: list[str],
    music_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    out_path: str,
    watermark_opacity: float = 0.6,
    sfx_paths: list[str] | None = None,
    sfx_gains_db: list[float] | None = None,
) -> None:
    """Produce final video with loudnorm, watermark, subtitles, music, SFX.

    Steps:
    1. Concat chapter files to a temp intermediate (stream copy).
    2. Loudnorm pass 1 to measure integrated loudness.
    3. Build filter graph for watermark, subtitles, music, and SFX mix.
    4. Encode: libx264 CRF 18 slow, AAC 384k 48kHz, +faststart, -14 LUFS.

    Raises:
        RuntimeError: If any FFmpeg call exits non-zero.
    """
    sfx_paths = sfx_paths or []
    sfx_gains_db = sfx_gains_db or []
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        concat_tmp = f.name

    try:
        await concat_chapter(chapter_paths, concat_tmp)
        stats = await loudnorm_pass1(concat_tmp)
        probe = await async_ffprobe(concat_tmp)
        duration_s = float(probe.get('format', {}).get('duration', 0.0) or 0.0)

        inputs = ['-i', concat_tmp]
        for mp in music_paths:
            inputs += ['-i', mp]
        for sp in sfx_paths:
            inputs += ['-i', sp]
        if watermark_path:
            inputs += ['-i', watermark_path]

        cmd = _build_final_pass_cmd(
            inputs=inputs,
            music_paths=music_paths,
            music_gains_db=music_gains_db,
            sfx_paths=sfx_paths,
            sfx_gains_db=sfx_gains_db,
            ass_path=ass_path,
            watermark_path=watermark_path,
            loudnorm_af=_loudnorm_audio_filter(stats),
            out_path=out_path,
            duration_s=duration_s,
        )
        await _run_ffmpeg_cmd(cmd, label='final_pass')
    finally:
        await asyncio.to_thread(Path(concat_tmp).unlink, missing_ok=True)
