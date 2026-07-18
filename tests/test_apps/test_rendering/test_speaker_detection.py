"""Tests for SpeakerDetectionService."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        result = svc._detect_from_video(
            Path('/fake.mp4'),
            0.0,
            60.0,
            target_width=1080,
            target_height=1920,
        )
    assert result.face_detected is False
    assert result.confidence == 0.0


def test_center_fallback_default() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback()
    assert result.face_detected is False
    assert result.crop_x + result.crop_w <= 1920
    assert result.crop_h == 1080


def test_center_fallback_custom_dimensions() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback(frame_w=1280, frame_h=720)
    assert result.crop_w == int(720 * 1080 / 1920)
    assert result.crop_h == 720


def test_center_fallback_landscape_target_is_full_frame() -> None:
    """A 16:9 target on a 16:9 source crops nothing."""
    svc = SpeakerDetectionService()
    result = svc._center_fallback(
        frame_w=1920,
        frame_h=1080,
        target_width=1920,
        target_height=1080,
    )
    assert (result.crop_w, result.crop_h) == (1920, 1080)
    assert (result.crop_x, result.crop_y) == (0, 0)


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
    mock_cap.get.side_effect = [30.0, 1920, 1080]
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
        result = svc._mediapipe_detect(
            Path('/fake.mp4'),
            0.0,
            30.0,
            target_width=1080,
            target_height=1920,
        )

    assert result.face_detected is False
    assert result.confidence == 0.0


def test_mediapipe_detect_with_faces() -> None:
    svc = SpeakerDetectionService()

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cap.get.side_effect = [30.0, 1920, 1080]
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
        result = svc._mediapipe_detect(
            Path('/fake.mp4'),
            0.0,
            1.0,
            target_width=1080,
            target_height=1920,
        )

    assert result.face_detected is True
    assert result.crop_w > 0
    assert result.crop_h == 1080


def test_get_detector_uses_cache() -> None:
    svc = SpeakerDetectionService()
    cached = MagicMock()
    svc._detector_cache = cached
    assert svc._get_detector() is cached


def test_get_detector_uses_baked_model_path(tmp_path: Path) -> None:
    svc = SpeakerDetectionService()
    mock_vision = MagicMock()
    mock_mp_python = MagicMock()
    baked_path = tmp_path / 'baked' / 'blaze_face_short_range.tflite'
    baked_path.parent.mkdir(parents=True)
    baked_path.write_bytes(b'fake')

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
        patch.dict(
            'os.environ',
            {'MEDIAPIPE_FACE_MODEL_PATH': str(baked_path)},
        ),
        patch('urllib.request.urlretrieve') as mock_urlretrieve,
    ):
        svc._get_detector()

    assert svc._detector_cache is not None
    assert not mock_urlretrieve.called


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
