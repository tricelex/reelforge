"""QC stage — FFmpeg/ffprobe quality checks on the final video."""

import asyncio
import contextlib
import re
import tempfile
from pathlib import Path
from typing import Any, ClassVar, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_DURATION_DRIFT_MAX = 0.03
_SILENCE_MAX_S = 1.8
_BLACK_FREEZE_MAX_S = 0.5
# Fraction of max luma below which a pixel counts as "black" for
# blackdetect. ffmpeg's default (0.1) also flags genuinely dark but
# detailed cinematography (night scenes, dim interiors) as broken output.
# Verified against a real run: 0.1 flagged 7 clearly-intentional dark
# narrative shots; 0.03 cleared every one of them while still catching
# a truly blank (near-RGB-0) frame.
_BLACK_PIX_TH = 0.03
# Ken Burns / static documentary holds look "frozen" to freezedetect.
# Detect from 8s, but only hard-fail stuck holds beyond a scene-length
# budget so normal longform stills do not block publish.
_FREEZE_DETECT_S = 8.0
_FREEZE_FAIL_S = 20.0
_FREEZE_NOISE_DB = -40
_LOUDNESS_TARGET_I = -14.0
_LOUDNESS_TOLERANCE = 0.7
_LOUDNESS_MAX_TP = -1.0
_FPS_EXPECTED = 30.0


async def _fetch_asset_to_tempfile(asset_id: str) -> str:
    """Download Asset content to a named temp file; return the file path."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    content: bytes = await asyncio.to_thread(asset.file.read)
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(content)
        return f.name


def _check_duration_drift(
    actual_s: float,
    expected_s: float,
) -> dict[str, Any] | None:
    """Return failure dict if drift > 3%, else None."""
    if expected_s <= 0:
        return None
    drift = abs(actual_s - expected_s) / expected_s
    if drift > _DURATION_DRIFT_MAX:
        return {
            'check': 'duration_drift',
            'actual_s': actual_s,
            'expected_s': expected_s,
            'drift_pct': round(drift * 100, 2),
        }
    return None


def _parse_fps(r_frame_rate: str) -> float:
    """Parse 'num/den' frame rate string to float."""
    if '/' in r_frame_rate:
        num, den = r_frame_rate.split('/')
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(r_frame_rate)


async def _run_silence_detect(path: str) -> list[dict[str, float]]:
    """Run silencedetect; return list of {start, end, duration} events."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-af',
        'silencedetect=noise=-50dB:d=1.8',
        '-f',
        'null',
        '-',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode()
    events: list[dict[str, float]] = []
    starts = re.findall(r'silence_start: ([\d.]+)', text)
    ends = re.findall(r'silence_end: ([\d.]+)', text)
    durations = re.findall(r'silence_duration: ([\d.]+)', text)
    for s, e, d in zip(starts, ends, durations, strict=False):
        events.append({
            'start': float(s),
            'end': float(e),
            'duration': float(d),
        })
    return events


async def _run_black_detect(path: str) -> list[dict[str, float]]:
    """Run blackdetect; return list of {start, end, duration} events."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-vf',
        f'blackdetect=d=0.5:pix_th={_BLACK_PIX_TH}',
        '-f',
        'null',
        '-',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode()
    events: list[dict[str, float]] = [
        {
            'start': float(m.group(1)),
            'end': float(m.group(2)),
            'duration': float(m.group(3)),
        }
        for m in re.finditer(
            r'black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)',
            text,
        )
    ]
    return events


async def _run_freeze_detect(path: str) -> list[dict[str, float]]:
    """Run freezedetect; return freeze events longer than ``_FREEZE_DETECT_S``."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-vf',
        f'freezedetect=n={_FREEZE_NOISE_DB}dB:d={_FREEZE_DETECT_S}',
        '-f',
        'null',
        '-',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode()
    events: list[dict[str, float]] = []
    for m in re.finditer(
        r'freeze_start: ([\d.]+).*?freeze_end: ([\d.]+)',
        text,
        re.DOTALL,
    ):
        duration = float(m.group(2)) - float(m.group(1))
        if duration > _FREEZE_DETECT_S:
            events.append({
                'start': float(m.group(1)),
                'end': float(m.group(2)),
                'duration': duration,
            })
    return events


async def _run_loudness_check(path: str) -> dict[str, float]:
    """Measure EBU R128 loudness via ebur128 filter; return {integrated, tp}."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-af',
        'ebur128=framelog=verbose',
        '-f',
        'null',
        '-',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode()
    integrated: float = _LOUDNESS_TARGET_I
    tp: float = _LOUDNESS_MAX_TP
    for line in text.splitlines():
        if 'I:' in line and 'LUFS' in line:
            with contextlib.suppress(IndexError, ValueError):
                integrated = float(
                    line.split('I:')[1].split('LUFS')[0].strip(),
                )
        if 'True peak:' in line:
            with contextlib.suppress(IndexError, ValueError):
                tp = float(
                    line.split('True peak:')[1].split('dBFS')[0].strip(),
                )
    return {'integrated': integrated, 'tp': tp}


def _probe_stream_failures(
    probe: dict[str, Any],
    expected_duration: float,
) -> tuple[float, list[dict[str, Any]]]:
    """Return duration and failures from ffprobe stream/format checks."""
    failures: list[dict[str, Any]] = []
    actual_duration = float(probe.get('format', {}).get('duration', 0.0))
    streams = probe.get('streams', [])
    video_streams = [s for s in streams if s.get('codec_type') == 'video']
    audio_streams = [s for s in streams if s.get('codec_type') == 'audio']

    drift_fail = _check_duration_drift(actual_duration, expected_duration)
    if drift_fail:
        failures.append(drift_fail)

    if not audio_streams:
        failures.append({'check': 'av_sync', 'reason': 'no_audio_stream'})
    if not video_streams:
        failures.append({'check': 'av_sync', 'reason': 'no_video_stream'})
    else:
        fps = _parse_fps(video_streams[0].get('r_frame_rate', '0/1'))
        if abs(fps - _FPS_EXPECTED) > 0.1:
            failures.append({
                'check': 'av_sync',
                'reason': 'fps_mismatch',
                'actual_fps': fps,
                'expected_fps': _FPS_EXPECTED,
            })
    return actual_duration, failures


async def _collect_media_failures(
    video_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run silence/black/freeze detectors; return (failures, warnings).

    Short freezes are expected for documentary Ken Burns holds and are
    reported as warnings. Only freezes longer than ``_FREEZE_FAIL_S``
    hard-fail QC (stuck encode / dead picture).
    """
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    silences = await _run_silence_detect(video_path)
    failures.extend(
        {'check': 'dead_air', 'event': sil}
        for sil in silences
        if sil['duration'] > _SILENCE_MAX_S
    )

    blacks = await _run_black_detect(video_path)
    failures.extend(
        {'check': 'black_frames', 'event': blk}
        for blk in blacks
        if blk.get('duration', 0) > _BLACK_FREEZE_MAX_S
    )

    freezes = await _run_freeze_detect(video_path)
    for frz in freezes:
        entry: dict[str, Any] = {'check': 'frozen_frames', 'event': frz}
        if frz['duration'] > _FREEZE_FAIL_S:
            failures.append(entry)
        else:
            warnings.append(entry)
    return failures, warnings


def _loudness_failures(loudness: dict[str, float]) -> list[dict[str, Any]]:
    """Return loudness/true-peak QC failures, if any."""
    failures: list[dict[str, Any]] = []
    if abs(loudness['integrated'] - _LOUDNESS_TARGET_I) > _LOUDNESS_TOLERANCE:
        failures.append({
            'check': 'loudness',
            'integrated_lufs': loudness['integrated'],
            'target_lufs': _LOUDNESS_TARGET_I,
            'tolerance': _LOUDNESS_TOLERANCE,
        })
    if loudness['tp'] > _LOUDNESS_MAX_TP:
        failures.append({
            'check': 'true_peak',
            'tp_dbtp': loudness['tp'],
            'max_tp': _LOUDNESS_MAX_TP,
        })
    return failures


def _expected_transition_compression_s(
    ctx: StageContext,
    scenes: list[dict[str, Any]],
) -> float:
    """Return duration the assembled video's crossfades are meant to remove.

    Mirrors assembly's per-chapter transition selection: a chapter whose
    picked style isn't 'hard_cut' concatenates its scenes with xfade,
    which overlaps clips instead of placing them end to end, compressing
    that chapter's timeline by (scene_count - 1) * transition duration.
    Comparing raw narration length against actual output without this
    adjustment fails duration_drift on every video from a channel with no
    'hard_cut' in its transition pool, regardless of whether anything
    actually went wrong.
    """
    from server.apps.pipelines.stages.assembly import (  # noqa: PLC0415
        _TRANSITION_DURATION_S,
        _group_scenes_by_chapter,
        _pick_transition_style,
    )
    from server.apps.rendering.ffmpeg import (  # noqa: PLC0415
        _MIN_TRANSITION_SEGMENTS,
    )

    transition_pool = getattr(
        ctx.channel,
        'assembly_style_transition_styles',
        [],
    )
    compression = 0.0
    for ch_idx, ch_scenes in _group_scenes_by_chapter(scenes).items():
        if len(ch_scenes) < _MIN_TRANSITION_SEGMENTS:
            continue
        if _pick_transition_style(transition_pool, ch_idx) == 'hard_cut':
            continue
        compression += (len(ch_scenes) - 1) * _TRANSITION_DURATION_S
    return compression


def _expected_duration_s(ctx: StageContext) -> float:
    """Prefer alignment/outline length over assembly self-probe.

    Baseline is the sum of each scene's own (end_s - start_s), not the
    narration span (max end_s). Consecutive scenes routinely have small
    gaps between them (pauses in narration that no scene's word-aligned
    window covers), and assembly never renders that gap time - only the
    scenes themselves get muxed and concatenated. Comparing against the
    full span overstates expected duration by the sum of those gaps, on
    top of the crossfade compression already accounted for below.
    """
    scenes = ctx.upstream.get('alignment', {}).get('scenes', [])
    if scenes:
        raw = sum(
            float(s.get('end_s', 0.0)) - float(s.get('start_s', 0.0))
            for s in scenes
        )
        return raw - _expected_transition_compression_s(ctx, scenes)
    outline_target = ctx.upstream.get('outline', {}).get(
        'total_target_seconds',
    )
    if outline_target:
        return float(outline_target)
    return float(ctx.upstream.get('assembly', {}).get('duration_s', 0))


@register_stage
class QCStage(Stage):
    """Stage 14: quality control checks on the assembled final video."""

    key: ClassVar[str] = 'qc'
    queue: ClassVar[str] = 'render'
    max_retries: ClassVar[int] = 1
    timeout_s: ClassVar[int] = 600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run all 7 QC checks; raise FatalProviderError on any failure."""
        from server.apps.rendering import ffmpeg  # noqa: PLC0415

        assembly = ctx.upstream.get('assembly', {})
        final_asset_id: str = assembly['asset_id']
        expected_duration = _expected_duration_s(ctx)

        video_path = await _fetch_asset_to_tempfile(final_asset_id)
        loudness: dict[str, float] = {}
        actual_duration = 0.0
        failures: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        try:
            probe = await ffmpeg.async_ffprobe(video_path)
            actual_duration, failures = _probe_stream_failures(
                probe,
                expected_duration,
            )
            media_fails, media_warns = await _collect_media_failures(video_path)
            failures.extend(media_fails)
            warnings.extend(media_warns)
            loudness = await _run_loudness_check(video_path)
            failures.extend(_loudness_failures(loudness))
        finally:
            await asyncio.to_thread(Path(video_path).unlink, missing_ok=True)

        qc_report = {
            'actual_duration_s': actual_duration,
            'expected_duration_s': expected_duration,
            'loudness': loudness,
            'failures': failures,
            'warnings': warnings,
        }
        if failures:
            raise FatalProviderError(
                f'QC failed: {len(failures)} check(s) — '
                f'{[f["check"] for f in failures]}',
                provider='qc',
                error_code='QC_FAILED',
                details={'passed': False, 'qc_report': qc_report},
            )
        return {'passed': True, 'qc_report': qc_report}
