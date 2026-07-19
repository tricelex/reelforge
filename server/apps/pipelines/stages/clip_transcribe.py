"""ClipTranscribeStage — ElevenLabs Scribe transcribe+diarize + scene detect."""

import asyncio
import json
import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Any, override

import structlog
from django.conf import settings

from server.apps.generation.clients import elevenlabs as elevenlabs_client
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError
from server.common.subprocess_errors import raise_subprocess_failure

logger = structlog.get_logger(__name__)


def _extract_audio(video_path: str, audio_path: str) -> None:
    """Extract mono 16kHz MP3 from video for ElevenLabs Scribe."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffmpeg',
            '-y',
            '-i',
            video_path,
            '-ac',
            '1',
            '-ar',
            '16000',
            '-b:a',
            '32k',
            '-vn',
            audio_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise_subprocess_failure('ffmpeg', result)


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
    except Exception as exc:
        logger.warning(
            'clip_transcribe_scene_detect_failed',
            error=str(exc),
        )
        return []


#: Pause gap (seconds) that starts a new caption segment.
_SEGMENT_PAUSE_GAP_SEC = 0.6
#: Soft max words per caption segment before forcing a split.
_SEGMENT_MAX_WORDS = 24


def _build_enriched_transcript(
    transcript_json: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten ElevenLabs Scribe words into {word, start, end, speaker_id}."""
    return [
        {
            'word': w.get('text', ''),
            'start': float(w.get('start', 0)),
            'end': float(w.get('end', 0)),
            'speaker_id': w.get('speaker_id') or 'UNKNOWN',
        }
        for w in transcript_json.get('words', [])
        if w.get('type', 'word') == 'word'
    ]


def _build_caption_segments(
    enriched_words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group Scribe words into ASS-compatible segments.

    Splits on speaker changes, pause gaps, and a soft word-count bound so
    CaptionStage can render without a Whisper-style ``segments`` payload.
    """
    assert isinstance(enriched_words, list), 'enriched_words must be a list'  # noqa: S101
    if not enriched_words:
        return []

    segments: list[dict[str, Any]] = []
    current_words: list[dict[str, Any]] = []
    current_speaker: str | None = None

    def _flush() -> None:
        if not current_words:
            return
        parts = [
            str(w.get('word', '')).strip()
            for w in current_words
            if w.get('word')
        ]
        segments.append({
            'text': ' '.join(parts).strip(),
            'start': float(current_words[0]['start']),
            'end': float(current_words[-1]['end']),
            'words': list(current_words),
        })
        current_words.clear()

    max_words = len(enriched_words)
    for idx, word in enumerate(enriched_words):
        assert idx < max_words, f'word index exceeded bound: {idx}'  # noqa: S101
        speaker = str(word.get('speaker_id') or 'UNKNOWN')
        if _should_split_segment(
            current_words,
            current_speaker,
            word,
            speaker,
        ):
            _flush()
        current_words.append(word)
        current_speaker = speaker

    _flush()
    assert len(segments) <= max_words, 'segment count exceeded word count'  # noqa: S101
    return segments


def _should_split_segment(
    current_words: list[dict[str, Any]],
    current_speaker: str | None,
    word: dict[str, Any],
    speaker: str,
) -> bool:
    if not current_words:
        return False
    prev = current_words[-1]
    gap = float(word['start']) - float(prev['end'])
    speaker_changed = speaker != current_speaker
    too_long = len(current_words) >= _SEGMENT_MAX_WORDS
    return speaker_changed or gap >= _SEGMENT_PAUSE_GAP_SEC or too_long


def _with_caption_segments(
    transcript_json: dict[str, Any],
    enriched_words: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return transcript JSON with ASS-compatible ``segments`` populated."""
    adapted = dict(transcript_json)
    existing = adapted.get('segments')
    if isinstance(existing, list) and existing:
        return adapted
    adapted['segments'] = _build_caption_segments(enriched_words)
    return adapted


@register_stage
class ClipTranscribeStage(Stage):
    """Stage 2: transcribe+diarize + scene detection → transcript assets."""

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
            'source_duration_sec',
            0.0,
        )
        api_key: str = getattr(settings, 'ELEVENLABS_API_KEY', '')
        if not api_key:
            raise FatalProviderError(
                'ELEVENLABS_API_KEY is not configured',
                provider='elevenlabs',
                error_code='missing_api_key',
            )

        source_asset = await Asset.objects.aget(id=source_asset_id)
        video_bytes = await asyncio.to_thread(source_asset.file.read)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video_path = str(tmp / 'source.mp4')
            audio_path = tmp / 'audio.mp3'
            await asyncio.to_thread(
                (tmp / 'source.mp4').write_bytes,
                video_bytes,
            )
            logger.info('clip_transcribe_extract_audio', run_id=str(ctx.run.id))
            await asyncio.to_thread(_extract_audio, video_path, str(audio_path))
            logger.info('clip_transcribe_scribe', run_id=str(ctx.run.id))
            transcript_json = await elevenlabs_client.transcribe(
                audio_path,
                api_key,
            )
            logger.info(
                'clip_transcribe_scene_detect',
                run_id=str(ctx.run.id),
            )
            scene_cuts = await asyncio.to_thread(
                _run_scene_detection,
                video_path,
            )

        transcript_text = transcript_json.get('text', '')
        enriched = _build_enriched_transcript(transcript_json)
        caption_ready = _with_caption_segments(transcript_json, enriched)

        manifest: dict[str, Any] = {
            'transcript_text': transcript_text,
            'transcript_json': caption_ready,
            'enriched_transcript': enriched,
            'scene_cuts': scene_cuts,
            'source_duration_sec': source_duration_sec,
        }

        transcript_asset = await ctx.assets.save(
            kind=AssetKind.TRANSCRIPT,
            content=json.dumps(caption_ready).encode(),
            filename='transcript.json',
            mime='application/json',
        )
        manifest_asset = await ctx.assets.save(
            kind=AssetKind.DOC,
            content=json.dumps(manifest).encode(),
            filename='analysis_manifest.json',
            mime='application/json',
        )

        duration_sec = float(
            transcript_json.get('audio_duration_secs', source_duration_sec),
        )
        await ctx.costs.record(
            provider='elevenlabs',
            operation='scribe_transcription',
            units=duration_sec / 60.0,
            unit_cost_usd=elevenlabs_client.SCRIBE_COST_PER_MINUTE_USD,
        )

        return {
            'source_asset_id': source_asset_id,
            'transcript_asset_id': str(transcript_asset.id),
            'manifest_asset_id': str(manifest_asset.id),
            'transcript_text': transcript_text,
            'scene_cuts': scene_cuts,
            'source_duration_sec': source_duration_sec,
            'transcription_cost_usd': str(
                elevenlabs_client.calculate_transcription_cost(duration_sec),
            ),
        }
