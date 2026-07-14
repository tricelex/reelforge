"""Tests for SpeakerDetectionService."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering import speaker_detection as speaker_detection_module
from server.apps.rendering.speaker_detection import (
    SpeakerCropResult,
    SpeakerDetectionService,
    preload_diarization_pipeline,
)


def _reset_diarization_pipeline_cache() -> None:
    speaker_detection_module._diarization_pipeline = None


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


def test_diarize_returns_segments() -> None:
    _reset_diarization_pipeline_cache()
    svc = SpeakerDetectionService()

    mock_turn_a = MagicMock()
    mock_turn_a.start = 0.0
    mock_turn_a.end = 5.0
    mock_output = MagicMock()
    mock_output.speaker_diarization = [(mock_turn_a, 'SPEAKER_A')]
    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock(return_value=mock_diarizer_instance)
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    audio_in_memory = {
        'waveform': MagicMock(),
        'sample_rate': 16000,
    }

    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    with (
        patch.dict(
            sys.modules,
            {
                'pyannote': MagicMock(),
                'pyannote.audio': mock_pyannote_audio,
            },
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value=audio_in_memory,
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
        patch('subprocess.run') as mock_run,
        patch('tempfile.NamedTemporaryFile') as mock_tmp,
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.name = '/tmp/test_audio.wav'
        mock_tmp.return_value = mock_ctx

        with patch('pathlib.Path.unlink'):
            result = svc.diarize(Path('/fake.mp4'))

    mock_pipeline_cls.from_pretrained.assert_called_once_with(
        'pyannote/speaker-diarization-community-1',
        token='hf-test-token',
    )
    mock_diarizer_instance.assert_called_once_with(audio_in_memory)
    assert len(result) == 1
    assert result[0]['speaker_id'] == 'SPEAKER_A'
    assert result[0]['start'] == 0.0
    assert result[0]['end'] == 5.0


def test_diarization_pipeline_loaded_once() -> None:
    _reset_diarization_pipeline_cache()
    svc = SpeakerDetectionService()

    mock_turn = MagicMock()
    mock_turn.start = 0.0
    mock_turn.end = 1.0
    mock_output = MagicMock()
    mock_output.speaker_diarization = [(mock_turn, 'SPEAKER_A')]
    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock(return_value=mock_diarizer_instance)
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    audio_in_memory = {
        'waveform': MagicMock(),
        'sample_rate': 16000,
    }

    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    with (
        patch.dict(
            sys.modules,
            {
                'pyannote': MagicMock(),
                'pyannote.audio': mock_pyannote_audio,
            },
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value=audio_in_memory,
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
        patch('subprocess.run') as mock_run,
        patch('tempfile.NamedTemporaryFile') as mock_tmp,
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.name = '/tmp/test_audio.wav'
        mock_tmp.return_value = mock_ctx

        with patch('pathlib.Path.unlink'):
            svc.diarize(Path('/fake.mp4'))
            svc.diarize(Path('/fake.mp4'))

    mock_pipeline_cls.from_pretrained.assert_called_once_with(
        'pyannote/speaker-diarization-community-1',
        token='hf-test-token',
    )
    assert mock_diarizer_instance.call_count == 2


def test_diarize_requires_huggingface_token() -> None:
    svc = SpeakerDetectionService()
    with patch(
        'django.conf.settings.HUGGINGFACE_TOKEN',
        '',
        create=True,
    ):
        try:
            svc.diarize(Path('/fake.mp4'))
            raise AssertionError('expected FatalProviderError')
        except Exception as exc:
            from server.common.exceptions import FatalProviderError

            assert isinstance(exc, FatalProviderError)
            assert exc.error_code == 'missing_hf_token'


def test_preload_diarization_pipeline_skips_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('DIARIZATION_PRELOAD', raising=False)
    assert preload_diarization_pipeline() is False


def test_preload_diarization_pipeline_loads_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_diarization_pipeline_cache()
    monkeypatch.setenv('DIARIZATION_PRELOAD', '1')
    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = MagicMock()
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    with (
        patch.dict(
            sys.modules,
            {
                'pyannote': MagicMock(),
                'pyannote.audio': mock_pyannote_audio,
            },
        ),
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
    ):
        assert preload_diarization_pipeline() is True
        assert preload_diarization_pipeline() is True

    mock_pipeline_cls.from_pretrained.assert_called_once_with(
        'pyannote/speaker-diarization-community-1',
        token='hf-test-token',
    )
