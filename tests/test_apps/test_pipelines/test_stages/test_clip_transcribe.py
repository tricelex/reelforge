"""Tests for ClipTranscribeStage."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_transcribe import (
    ClipTranscribeStage,
    _build_enriched_transcript,
    _extract_audio,
    _run_scene_detection,
    _run_whisperx,
    _try_scene_detect,
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
        'segments': [
            {
                'speaker': 'SPEAKER_A',
                'text': 'Hello world',
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 0.5},
                    {'word': 'world', 'start': 0.5, 'end': 1.0},
                ],
            },
        ],
    }
    result = _build_enriched_transcript(transcript)
    assert len(result) == 2
    assert result[0] == {
        'word': 'Hello',
        'start': 0.0,
        'end': 0.5,
        'speaker_id': 'SPEAKER_A',
    }


def test_build_enriched_transcript_default_speaker() -> None:
    transcript = {
        'segments': [
            {'text': 'Hi', 'words': [{'word': 'Hi', 'start': 0.0, 'end': 0.3}]},
        ],
    }
    result = _build_enriched_transcript(transcript)
    assert result[0]['speaker_id'] == 'UNKNOWN'


def test_build_enriched_transcript_empty() -> None:
    assert _build_enriched_transcript({}) == []
    assert _build_enriched_transcript({'segments': []}) == []


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
        _extract_audio('/video.mp4', '/audio.wav')
    except RuntimeError as exc:
        assert 'ffmpeg failed' in str(exc)
        assert 'invalid data' in str(exc)
    else:
        raise AssertionError('expected RuntimeError')


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_run_whisperx_raises_with_both_attempt_stderr(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.side_effect = [
        MagicMock(returncode=1, stderr='diarize failed', stdout=''),
        MagicMock(returncode=1, stderr='module not found', stdout=''),
    ]
    with patch(
        'server.apps.pipelines.stages.clip_transcribe.tempfile.mkdtemp',
    ) as mock_mkdtemp:
        mock_mkdtemp.return_value = str(tmp_path)
        try:
            _run_whisperx(str(tmp_path / 'audio.wav'))
        except RuntimeError as exc:
            assert 'diarize failed' in str(exc)
            assert 'module not found' in str(exc)
        else:
            raise AssertionError('expected RuntimeError')


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_extract_audio_calls_ffmpeg(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    _extract_audio('/video.mp4', '/audio.wav')
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert 'ffmpeg' in cmd
    assert '-vn' in cmd


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_run_whisperx_success(mock_run: MagicMock, tmp_path: Path) -> None:
    transcript_data = {'segments': [{'text': 'hello'}]}
    out_file = tmp_path / 'audio.json'
    out_file.write_text(json.dumps(transcript_data))

    mock_run.return_value = MagicMock(returncode=0)
    with patch(
        'server.apps.pipelines.stages.clip_transcribe.tempfile.mkdtemp',
    ) as mock_mkdtemp:
        mock_mkdtemp.return_value = str(tmp_path)
        result = _run_whisperx(str(tmp_path / 'audio.wav'))

    assert result == transcript_data


@patch('server.apps.pipelines.stages.clip_transcribe.subprocess.run')
def test_run_whisperx_fallback_without_diarize(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    transcript_data = {'segments': [{'text': 'fallback'}]}
    out_file = tmp_path / 'audio.json'
    out_file.write_text(json.dumps(transcript_data))

    mock_run.side_effect = [
        MagicMock(returncode=1, stderr='diarize failed'),
        MagicMock(returncode=0, stdout=''),
    ]

    with patch(
        'server.apps.pipelines.stages.clip_transcribe.tempfile.mkdtemp',
    ) as mock_mkdtemp:
        mock_mkdtemp.return_value = str(tmp_path)
        result = _run_whisperx(str(tmp_path / 'audio.wav'))

    assert result == transcript_data
    assert mock_run.call_count == 2


def test_clip_transcribe_run() -> None:
    ctx = MagicMock()
    ctx.upstream = {
        'clip_ingest': {
            'asset_id': 'src-asset-id',
            'source_duration_sec': 60.0,
        },
    }

    transcript_data: dict = {
        'segments': [{'text': 'hello', 'speaker': 'A', 'words': []}],
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
                        transcript_data,  # whisperx
                        [5.0, 10.0],  # scene_detection
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(
                return_value=fake_source_asset,
            )
            ctx.assets.save = AsyncMock(
                side_effect=[fake_transcript_asset, fake_manifest_asset],
            )
            return await ClipTranscribeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['transcript_asset_id'] == 'transcript-asset-id'
    assert result['manifest_asset_id'] == 'manifest-asset-id'
    assert result['scene_cuts'] == [5.0, 10.0]
    assert result['source_duration_sec'] == 60.0
