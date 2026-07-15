"""Tests for SpeakerDetectionService."""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering import speaker_detection as speaker_detection_module
from server.apps.rendering.speaker_detection import (
    SpeakerCropResult,
    SpeakerDetectionService,
)


def test_detect_with_manual_crop() -> None:
    svc = SpeakerDetectionService()
    result = svc.detect(
        video_path=Path('/fake.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=540,
        manual_crop_h=960,
    )
    assert result.face_detected is True
    assert result.confidence == 1.0
    assert result.crop_x == 100


def test_detect_falls_back_to_center_on_error() -> None:
    svc = SpeakerDetectionService()
    with patch.object(
        svc,
        '_mediapipe_detect',
        side_effect=RuntimeError('no mediapipe'),
    ):
        result = svc._detect_from_video(Path('/fake.mp4'), 0.0, 60.0)
    assert result.face_detected is False
    assert result.confidence == 0.0


def test_center_fallback_default() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback()
    assert result.face_detected is False
    assert result.crop_x + result.crop_w <= 1920


def test_center_fallback_custom_width() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback(frame_w=1280)
    assert result.crop_w == int(1280 * 9 / 16)


def test_speaker_crop_result_is_frozen() -> None:
    import pytest

    result = SpeakerCropResult(
        crop_x=0,
        crop_w=540,
        crop_h=960,
        confidence=1.0,
        face_detected=True,
    )
    with pytest.raises(Exception):
        result.crop_x = 100  # type: ignore[misc]


def test_detect_without_manual_crop_falls_back_on_error() -> None:
    svc = SpeakerDetectionService()
    with patch.object(
        svc,
        '_mediapipe_detect',
        side_effect=RuntimeError('no cv2'),
    ):
        result = svc.detect(
            video_path=Path('/fake.mp4'),
            start_sec=0.0,
            end_sec=60.0,
        )
    assert result.face_detected is False


def test_mediapipe_detect_with_no_faces() -> None:
    svc = SpeakerDetectionService()

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cap.get.side_effect = [30.0, 1920]
    mock_cap.read.return_value = (False, None)

    mock_np = MagicMock()
    mock_mp = MagicMock()
    detection_result = MagicMock()
    detection_result.detections = []
    mock_mp.Image.return_value = MagicMock()

    with (
        patch.dict(
            sys.modules,
            {
                'cv2': mock_cv2,
                'numpy': mock_np,
                'mediapipe': mock_mp,
            },
        ),
        patch.object(svc, '_get_detector', return_value=MagicMock()),
    ):
        result = svc._mediapipe_detect(Path('/fake.mp4'), 0.0, 30.0)

    assert result.face_detected is False
    assert result.confidence == 0.0


def test_mediapipe_detect_with_faces() -> None:
    svc = SpeakerDetectionService()

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cap.get.side_effect = [30.0, 1920]
    mock_cap.read.side_effect = [(True, MagicMock()), (False, None)]
    mock_cv2.cvtColor.return_value = MagicMock()

    bbox = MagicMock()
    bbox.origin_x = 800
    bbox.width = 320
    det = MagicMock()
    det.bounding_box = bbox
    mock_detection_result = MagicMock()
    mock_detection_result.detections = [det]
    mock_detector = MagicMock()
    mock_detector.detect.return_value = mock_detection_result

    mock_np = MagicMock()
    mock_np.median.return_value = 960.0
    mock_mp = MagicMock()

    with (
        patch.dict(
            sys.modules,
            {
                'cv2': mock_cv2,
                'numpy': mock_np,
                'mediapipe': mock_mp,
            },
        ),
        patch.object(svc, '_get_detector', return_value=mock_detector),
    ):
        result = svc._mediapipe_detect(Path('/fake.mp4'), 0.0, 1.0)

    assert result.face_detected is True
    assert result.crop_w > 0


def test_get_detector_uses_cache() -> None:
    svc = SpeakerDetectionService()
    cached = MagicMock()
    svc._detector_cache = cached
    assert svc._get_detector() is cached


def test_get_detector_loads_model(tmp_path: Path) -> None:
    svc = SpeakerDetectionService()
    mock_vision = MagicMock()
    mock_mp_python = MagicMock()
    # Pre-create the model file so exists() returns True (no download path)
    model_dir = tmp_path / '.cache' / 'mediapipe'
    model_dir.mkdir(parents=True)
    (model_dir / 'blaze_face_short_range.tflite').write_bytes(b'fake')

    with (
        patch.dict(
            sys.modules,
            {
                'mediapipe.tasks': MagicMock(),
                'mediapipe.tasks.python': mock_mp_python,
                'mediapipe.tasks.python.vision': mock_vision,
                'urllib.request': MagicMock(),
            },
        ),
        patch('pathlib.Path.home', return_value=tmp_path),
    ):
        svc._get_detector()

    assert svc._detector_cache is not None


def test_get_detector_downloads_model_when_missing(tmp_path: Path) -> None:
    svc = SpeakerDetectionService()
    mock_vision = MagicMock()
    mock_mp_python = MagicMock()
    # Do NOT create the model file — exists() will return False

    with (
        patch.dict(
            sys.modules,
            {
                'mediapipe.tasks': MagicMock(),
                'mediapipe.tasks.python': mock_mp_python,
                'mediapipe.tasks.python.vision': mock_vision,
            },
        ),
        patch('pathlib.Path.home', return_value=tmp_path),
        patch('urllib.request.urlretrieve') as mock_urlretrieve,
    ):
        svc._get_detector()

    assert mock_urlretrieve.called
    assert svc._detector_cache is not None


def test_diarize_requires_api_key() -> None:
    from server.common.exceptions import FatalProviderError

    svc = SpeakerDetectionService()
    with (
        patch(
            'django.conf.settings.PYANNOTEAI_API_KEY',
            '',
            create=True,
        ),
        pytest.raises(FatalProviderError) as exc_info,
    ):
        svc.diarize(Path('/fake.mp4'))

    assert exc_info.value.error_code == 'missing_api_key'


def _mock_pyannoteai_sdk_module(
    *,
    diarization: list[dict[str, Any]],
) -> tuple[MagicMock, MagicMock]:
    """Build a fake `pyannoteai.sdk` module whose Client returns `diarization`."""
    mock_client_instance = MagicMock()
    mock_client_instance.upload.return_value = 'media://fake-hash'
    mock_client_instance.diarize.return_value = 'job-123'
    mock_client_instance.retrieve.return_value = {
        'output': {'diarization': diarization},
    }
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_sdk_module = MagicMock()
    mock_sdk_module.Client = mock_client_cls
    return mock_client_cls, mock_sdk_module


def test_diarize_uploads_submits_and_maps_segments() -> None:
    svc = SpeakerDetectionService()
    diarization = [
        {'start': 0.0, 'end': 5.0, 'speaker': 'SPEAKER_00'},
        {'start': 5.0, 'end': 10.0, 'speaker': 'SPEAKER_01'},
    ]
    mock_client_cls, mock_sdk_module = _mock_pyannoteai_sdk_module(
        diarization=diarization,
    )

    with (
        patch.dict(
            sys.modules,
            {'pyannoteai': MagicMock(), 'pyannoteai.sdk': mock_sdk_module},
        ),
        patch('subprocess.run') as mock_run,
        patch(
            'django.conf.settings.PYANNOTEAI_API_KEY',
            'pyannoteai-test-key',
            create=True,
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = svc.diarize(Path('/fake.mp4'))

    assert result == [
        {'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0},
        {'speaker_id': 'SPEAKER_01', 'start': 5.0, 'end': 10.0},
    ]
    mock_client_cls.assert_called_once_with('pyannoteai-test-key')
    client = mock_client_cls.return_value
    client.upload.assert_called_once()
    client.diarize.assert_called_once_with(
        'media://fake-hash',
        model=speaker_detection_module._PYANNOTEAI_MODEL,
    )
    client.retrieve.assert_called_once_with('job-123')

    ffmpeg_cmd = mock_run.call_args.args[0]
    assert ffmpeg_cmd[0] == 'ffmpeg'
    assert '-ac' in ffmpeg_cmd
    assert '16000' in ffmpeg_cmd
    assert '-vn' in ffmpeg_cmd


def test_diarize_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SpeakerDetectionService()
    diarization = [{'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}]
    mock_client_cls, mock_sdk_module = _mock_pyannoteai_sdk_module(
        diarization=diarization,
    )
    monkeypatch.setattr(speaker_detection_module, '_PYANNOTEAI_MODEL', 'community-1')

    with (
        patch.dict(
            sys.modules,
            {'pyannoteai': MagicMock(), 'pyannoteai.sdk': mock_sdk_module},
        ),
        patch('subprocess.run') as mock_run,
        patch(
            'django.conf.settings.PYANNOTEAI_API_KEY',
            'pyannoteai-test-key',
            create=True,
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        svc.diarize(Path('/fake.mp4'))

    client = mock_client_cls.return_value
    client.diarize.assert_called_once_with('media://fake-hash', model='community-1')


def test_diarize_propagates_job_failure() -> None:
    svc = SpeakerDetectionService()
    mock_client_instance = MagicMock()
    mock_client_instance.upload.return_value = 'media://fake-hash'
    mock_client_instance.diarize.return_value = 'job-123'
    mock_client_instance.retrieve.side_effect = RuntimeError('job failed: boom')
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_sdk_module = MagicMock()
    mock_sdk_module.Client = mock_client_cls

    with (
        patch.dict(
            sys.modules,
            {'pyannoteai': MagicMock(), 'pyannoteai.sdk': mock_sdk_module},
        ),
        patch('subprocess.run') as mock_run,
        patch(
            'django.conf.settings.PYANNOTEAI_API_KEY',
            'pyannoteai-test-key',
            create=True,
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(RuntimeError, match='job failed'):
            svc.diarize(Path('/fake.mp4'))


def test_diarize_cleans_up_temp_audio_file() -> None:
    svc = SpeakerDetectionService()
    diarization = [{'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}]
    _mock_client_cls, mock_sdk_module = _mock_pyannoteai_sdk_module(
        diarization=diarization,
    )
    captured_path: dict[str, str] = {}

    def _fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
        captured_path['audio_path'] = cmd[-1]
        Path(cmd[-1]).write_bytes(b'fake-wav')
        return MagicMock(returncode=0)

    with (
        patch.dict(
            sys.modules,
            {'pyannoteai': MagicMock(), 'pyannoteai.sdk': mock_sdk_module},
        ),
        patch('subprocess.run', side_effect=_fake_run),
        patch(
            'django.conf.settings.PYANNOTEAI_API_KEY',
            'pyannoteai-test-key',
            create=True,
        ),
    ):
        svc.diarize(Path('/fake.mp4'))

    assert not Path(captured_path['audio_path']).exists()
