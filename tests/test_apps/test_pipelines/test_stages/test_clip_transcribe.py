"""Tests for ClipTranscribeStage."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_transcribe import (
    ClipTranscribeStage,
    _build_caption_segments,
    _build_enriched_transcript,
    _extract_audio,
    _run_scene_detection,
    _try_scene_detect,
    _with_caption_segments,
)


def test_clip_transcribe_attributes() -> None:
    assert ClipTranscribeStage.key == 'clip_transcribe'
    assert ClipTranscribeStage.queue == 'render'
    assert ClipTranscribeStage.max_retries == 2
    assert ClipTranscribeStage.timeout_s == 3600


def test_clip_transcribe_fan_out_returns_none() -> None:
    assert ClipTranscribeStage().fan_out(MagicMock()) is None


def test_clip_transcribe_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_transcribe' in STAGE_REGISTRY


def test_build_enriched_transcript_basic() -> None:
    transcript = {
        'words': [
            {
                'text': 'Hello',
                'start': 0.0,
                'end': 0.5,
                'type': 'word',
                'speaker_id': 'speaker_0',
            },
            {
                'text': 'world',
                'start': 0.5,
                'end': 1.0,
                'type': 'word',
                'speaker_id': 'speaker_0',
            },
        ],
    }
    result = _build_enriched_transcript(transcript)
    assert len(result) == 2
    assert result[0] == {
        'word': 'Hello',
        'start': 0.0,
        'end': 0.5,
        'speaker_id': 'speaker_0',
    }


def test_build_enriched_transcript_default_speaker() -> None:
    transcript = {
        'words': [{'text': 'Hi', 'start': 0.0, 'end': 0.3, 'type': 'word'}],
    }
    result = _build_enriched_transcript(transcript)
    assert result[0]['speaker_id'] == 'UNKNOWN'


def test_build_enriched_transcript_skips_non_word_entries() -> None:
    transcript = {
        'words': [
            {'text': ' ', 'start': 0.3, 'end': 0.4, 'type': 'spacing'},
            {
                'text': 'Hi',
                'start': 0.4,
                'end': 0.6,
                'type': 'word',
                'speaker_id': 'speaker_1',
            },
        ],
    }
    result = _build_enriched_transcript(transcript)
    assert len(result) == 1
    assert result[0]['word'] == 'Hi'


def test_build_enriched_transcript_empty() -> None:
    assert _build_enriched_transcript({}) == []
    assert _build_enriched_transcript({'words': []}) == []


def test_build_caption_segments_splits_on_pause_and_speaker() -> None:
    words = [
        {'word': 'Hello', 'start': 0.0, 'end': 0.3, 'speaker_id': 'A'},
        {'word': 'there', 'start': 0.3, 'end': 0.6, 'speaker_id': 'A'},
        {'word': 'Now', 'start': 2.0, 'end': 2.3, 'speaker_id': 'A'},
        {'word': 'what', 'start': 2.3, 'end': 2.5, 'speaker_id': 'B'},
    ]
    segments = _build_caption_segments(words)
    assert len(segments) == 3
    assert segments[0]['text'] == 'Hello there'
    assert segments[1]['text'] == 'Now'
    assert segments[2]['text'] == 'what'
    assert segments[0]['words'][0]['word'] == 'Hello'


def test_with_caption_segments_preserves_existing() -> None:
    existing = [{'text': 'keep', 'start': 0.0, 'end': 1.0, 'words': []}]
    result = _with_caption_segments(
        {'text': 'keep', 'segments': existing, 'words': []},
        [],
    )
    assert result['segments'] is existing


def test_with_caption_segments_builds_when_missing() -> None:
    transcript = {
        'text': 'Hello world',
        'words': [
            {
                'text': 'Hello',
                'start': 0.0,
                'end': 0.4,
                'type': 'word',
                'speaker_id': 'A',
            },
            {
                'text': 'world',
                'start': 0.4,
                'end': 0.8,
                'type': 'word',
                'speaker_id': 'A',
            },
        ],
    }
    enriched = _build_enriched_transcript(transcript)
    result = _with_caption_segments(transcript, enriched)
    assert len(result['segments']) == 1
    assert result['segments'][0]['text'] == 'Hello world'


def test_run_scene_detection_returns_empty_on_exception() -> None:
    with patch.dict(
        'sys.modules',
        {'scenedetect': None, 'scenedetect.detectors': None},
    ):
        result = _run_scene_detection('/nonexistent.mp4')
    assert result == []


def test_try_scene_detect_returns_cuts() -> None:
    fake_scene = MagicMock()
    fake_scene[0].get_seconds.return_value = 5.0
    fake_scene_b = MagicMock()
    fake_scene_b[0].get_seconds.return_value = 12.0

    fake_video = MagicMock()
    mock_scene_manager = MagicMock()
    mock_scene_manager.get_scene_list.return_value = [fake_scene, fake_scene_b]

    fake_scenedetect = MagicMock()
    fake_scenedetect.open_video.return_value = fake_video
    fake_scenedetect.SceneManager.return_value = mock_scene_manager
    fake_scenedetect.detectors = MagicMock()

    with patch.dict(
        sys.modules,
        {
            'scenedetect': fake_scenedetect,
            'scenedetect.detectors': fake_scenedetect.detectors,
        },
    ):
        result = _try_scene_detect('/video.mp4')

    assert result == [12.0]


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_extract_audio_raises_with_stderr(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=1,
        stderr='ffmpeg: invalid data',
        stdout='',
    )
    try:
        _extract_audio('/video.mp4', '/audio.mp3')
    except RuntimeError as exc:
        assert 'ffmpeg failed' in str(exc)
        assert 'invalid data' in str(exc)
    else:
        raise AssertionError('expected RuntimeError')


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_extract_audio_calls_ffmpeg(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    _extract_audio('/video.mp4', '/audio.mp3')
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert 'ffmpeg' in cmd
    assert '-vn' in cmd
    assert '32k' in cmd


def test_clip_transcribe_missing_api_key_raises_fatal() -> None:
    from server.common.exceptions import FatalProviderError

    ctx = MagicMock()

    async def _inner() -> None:
        with patch(
            'server.apps.pipelines.stages.clip_transcribe.settings',
        ) as mock_settings:
            mock_settings.ELEVENLABS_API_KEY = ''
            await ClipTranscribeStage().run(ctx)

    try:
        asyncio.run(_inner())
    except FatalProviderError as exc:
        assert exc.provider == 'elevenlabs'
        assert exc.error_code == 'missing_api_key'
    else:
        raise AssertionError('expected FatalProviderError')


def test_clip_transcribe_run() -> None:
    ctx = MagicMock()
    ctx.upstream = {
        'clip_ingest': {
            'asset_id': 'src-asset-id',
            'source_duration_sec': 60.0,
        },
    }

    transcript_data: dict = {
        'text': 'hello',
        'words': [
            {
                'text': 'hello',
                'start': 0.0,
                'end': 0.4,
                'type': 'word',
                'speaker_id': 'speaker_0',
            },
        ],
        'audio_duration_secs': 60.0,
    }
    fake_source_asset = MagicMock()
    fake_transcript_asset = MagicMock()
    fake_transcript_asset.id = 'transcript-asset-id'
    fake_manifest_asset = MagicMock()
    fake_manifest_asset.id = 'manifest-asset-id'

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch(
                'server.apps.pipelines.stages.clip_transcribe.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        b'video bytes',  # source_asset.file.read
                        None,  # write_bytes
                        None,  # extract_audio
                        [5.0, 10.0],  # scene_detection
                    ],
                ),
            ),
            patch(
                'server.apps.pipelines.stages.clip_transcribe.elevenlabs_client.transcribe',
                new=AsyncMock(return_value=transcript_data),
            ) as mock_transcribe,
            patch(
                'server.apps.pipelines.stages.clip_transcribe.settings',
            ) as mock_settings,
        ):
            mock_settings.ELEVENLABS_API_KEY = 'test-key'
            mock_asset_cls.objects.aget = AsyncMock(
                return_value=fake_source_asset,
            )
            ctx.assets.save = AsyncMock(
                side_effect=[fake_transcript_asset, fake_manifest_asset],
            )
            ctx.costs.record = AsyncMock()
            result = await ClipTranscribeStage().run(ctx)
            mock_transcribe.assert_called_once()
            return result

    result = asyncio.run(_inner())
    assert result['source_asset_id'] == 'src-asset-id'
    assert result['transcript_asset_id'] == 'transcript-asset-id'
    assert result['manifest_asset_id'] == 'manifest-asset-id'
    assert result['scene_cuts'] == [5.0, 10.0]
    assert result['source_duration_sec'] == 60.0
    ctx.costs.record.assert_called_once()
