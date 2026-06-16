"""ClipTranscribeStage — WhisperX + scene detection → transcript assets."""

import asyncio
import json
import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _extract_audio(video_path: str, audio_path: str) -> None:
    """Extract mono 16kHz WAV from video for WhisperX."""
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffmpeg', '-y', '-i', video_path,
            '-ac', '1', '-ar', '16000', '-vn', audio_path,
        ],
        check=True,
        capture_output=True,
    )


def _run_whisperx(audio_path: str, language: str = 'en') -> dict[str, Any]:
    """Run WhisperX; falls back without diarization on error."""
    out_dir = tempfile.mkdtemp()
    base_cmd = [
        'python', '-m', 'whisperx', audio_path,
        '--language', language,
        '--output_format', 'json',
        '--output_dir', out_dir,
    ]
    result = subprocess.run(  # noqa: S603
        [*base_cmd, '--diarize'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        subprocess.run(base_cmd, capture_output=True, text=True, check=True)  # noqa: S603
    out_file = Path(out_dir) / (Path(audio_path).stem + '.json')
    return json.loads(out_file.read_text())


def _try_scene_detect(video_path: str) -> list[float]:
    """Inner scene detection; called inside try in _run_scene_detection."""
    from scenedetect import SceneManager, open_video  # noqa: PLC0415
    from scenedetect.detectors import ContentDetector  # noqa: PLC0415

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video)
    scenes = scene_manager.get_scene_list()
    return [scene[0].get_seconds() for scene in scenes[1:]]


def _run_scene_detection(video_path: str) -> list[float]:
    """Return scene-cut timestamps in seconds; returns [] on any error."""
    try:
        return _try_scene_detect(video_path)
    except Exception:
        return []


def _build_enriched_transcript(
    transcript_json: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten word-level data into list of {word, start, end, speaker_id}."""
    words: list[dict[str, Any]] = []
    for seg in transcript_json.get('segments', []):
        speaker = seg.get('speaker', 'UNKNOWN')
        words.extend(
            {
                'word': w.get('word', ''),
                'start': float(w.get('start', 0)),
                'end': float(w.get('end', 0)),
                'speaker_id': speaker,
            }
            for w in seg.get('words', [])
        )
    return words


@register_stage
class ClipTranscribeStage(Stage):
    """Stage 2: transcription + scene detection → transcript assets."""

    key = 'clip_transcribe'
    queue = 'render'
    max_retries = 2
    timeout_s = 3600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Transcribe source video and persist transcript + manifest assets."""
        from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415

        source_asset_id: str = ctx.upstream['clip_ingest']['asset_id']
        source_duration_sec: float = ctx.upstream['clip_ingest'].get(
            'source_duration_sec', 0.0,
        )

        source_asset = await Asset.objects.aget(id=source_asset_id)
        video_bytes = await asyncio.to_thread(source_asset.file.read)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video_path = str(tmp / 'source.mp4')
            audio_path = str(tmp / 'audio.wav')
            await asyncio.to_thread(
                (tmp / 'source.mp4').write_bytes, video_bytes,
            )
            await asyncio.to_thread(_extract_audio, video_path, audio_path)
            transcript_json = await asyncio.to_thread(
                _run_whisperx, audio_path,
            )
            scene_cuts = await asyncio.to_thread(
                _run_scene_detection, video_path,
            )

        transcript_text = ' '.join(
            seg.get('text', '').strip()
            for seg in transcript_json.get('segments', [])
        )
        enriched = _build_enriched_transcript(transcript_json)

        manifest: dict[str, Any] = {
            'transcript_text': transcript_text,
            'transcript_json': transcript_json,
            'enriched_transcript': enriched,
            'scene_cuts': scene_cuts,
            'source_duration_sec': source_duration_sec,
        }

        transcript_asset = await ctx.assets.save(
            kind=AssetKind.TRANSCRIPT,
            content=json.dumps(transcript_json).encode(),
            filename='transcript.json',
            mime='application/json',
        )
        manifest_asset = await ctx.assets.save(
            kind=AssetKind.DOC,
            content=json.dumps(manifest).encode(),
            filename='analysis_manifest.json',
            mime='application/json',
        )

        return {
            'transcript_asset_id': str(transcript_asset.id),
            'manifest_asset_id': str(manifest_asset.id),
            'transcript_text': transcript_text,
            'scene_cuts': scene_cuts,
            'source_duration_sec': source_duration_sec,
        }
