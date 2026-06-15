"""Tests for SpeakerDetectionService."""

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
        svc, '_mediapipe_detect', side_effect=RuntimeError('no mediapipe'),
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
    result = SpeakerCropResult(
        crop_x=0, crop_w=540, crop_h=960, confidence=1.0, face_detected=True,
    )
    try:
        result.crop_x = 100  # type: ignore[misc]
        assert False, 'Should have raised'
    except Exception:
        pass
