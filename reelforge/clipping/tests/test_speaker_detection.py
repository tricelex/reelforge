from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pytest

from reelforge.services.media.speaker_detection import SpeakerCropResult
from reelforge.services.media.speaker_detection import SpeakerDetectionService


def _make_cv2_mock() -> MagicMock:
    """Build a mock cv2 module that can be injected into sys.modules."""
    cv2 = MagicMock()
    # Real cv2 integer constants used in speaker_detection.py
    cv2.CAP_PROP_FPS = 5
    cv2.CAP_PROP_FRAME_WIDTH = 3
    cv2.CAP_PROP_FRAME_HEIGHT = 4
    cv2.CAP_PROP_POS_FRAMES = 1
    cv2.COLOR_BGR2GRAY = 6
    cv2.FONT_HERSHEY_SIMPLEX = 0
    cv2.data = MagicMock()
    cv2.data.haarcascades = ""
    return cv2


def _make_mock_cap(
    cv2_mock: MagicMock,
    width: int = 1280,
    height: int = 720,
    fps: float = 30.0,
    frame_count: int = 150,
) -> MagicMock:
    """Return a mock VideoCapture that yields black frames."""
    cap = MagicMock()
    cap.get.side_effect = lambda prop: {
        cv2_mock.CAP_PROP_FRAME_WIDTH: width,
        cv2_mock.CAP_PROP_FRAME_HEIGHT: height,
        cv2_mock.CAP_PROP_FPS: fps,
    }.get(prop, 0)
    cap.isOpened.return_value = True
    black_frame = np.zeros((height, width, 3), dtype="uint8")
    reads = [(True, black_frame)] * frame_count + [(False, None)]
    cap.read.side_effect = reads
    return cap


def _make_face_cascade(face_x: int, face_w: int = 100, face_y: int = 100, face_h: int = 100) -> MagicMock:
    cascade = MagicMock()
    cascade.detectMultiScale.return_value = np.array([[face_x, face_y, face_w, face_h]])
    return cascade


def _make_no_face_cascade() -> MagicMock:
    cascade = MagicMock()
    cascade.detectMultiScale.return_value = np.array([])
    return cascade


def test_speaker_detection_returns_speaker_crop_result_dataclass() -> None:
    cv2_mock = _make_cv2_mock()
    cap = _make_mock_cap(cv2_mock)
    cv2_mock.VideoCapture.return_value = cap
    cv2_mock.CascadeClassifier.return_value = _make_face_cascade(face_x=230, face_w=100)

    with patch.dict(sys.modules, {"cv2": cv2_mock}):
        result = SpeakerDetectionService().detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    assert isinstance(result, SpeakerCropResult)
    assert result.face_detected is True
    assert result.confidence > 0.0


def test_speaker_detection_centers_on_face() -> None:
    """Face center at 25% of 1280px wide frame — crop_x should be shifted left of center."""
    # face_x=270, face_w=100 → center = 270+50 = 320 = 25% of 1280
    cv2_mock = _make_cv2_mock()
    cap = _make_mock_cap(cv2_mock, width=1280, height=720)
    cv2_mock.VideoCapture.return_value = cap
    cv2_mock.CascadeClassifier.return_value = _make_face_cascade(face_x=270, face_w=100)

    with patch.dict(sys.modules, {"cv2": cv2_mock}):
        result = SpeakerDetectionService(sample_every_n_frames=1).detect(
            Path("/tmp/fake.mp4"), 0.0, 5.0
        )

    # crop_w = int(9/16 * 720) = 405
    assert result.face_detected is True
    assert result.crop_w == 405
    assert result.crop_h == 720
    assert result.crop_x >= 0
    assert result.crop_x + result.crop_w <= 1280


def test_speaker_detection_falls_back_to_center_when_no_face() -> None:
    cv2_mock = _make_cv2_mock()
    cap = _make_mock_cap(cv2_mock, width=1280, height=720)
    cv2_mock.VideoCapture.return_value = cap
    cv2_mock.CascadeClassifier.return_value = _make_no_face_cascade()

    with patch.dict(sys.modules, {"cv2": cv2_mock}):
        result = SpeakerDetectionService().detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    assert result.face_detected is False
    assert result.confidence == 0.0
    # Center crop: crop_x = (1280 - 405) // 2 = 437
    assert result.crop_x == (1280 - 405) // 2


def test_speaker_crop_result_crop_x_clamped_to_valid_range() -> None:
    """Face at far right should not produce a crop that exceeds frame width."""
    # face_x=1200, face_w=60 → center = 1230 (near right edge of 1280px frame)
    cv2_mock = _make_cv2_mock()
    cap = _make_mock_cap(cv2_mock, width=1280, height=720)
    cv2_mock.VideoCapture.return_value = cap
    cv2_mock.CascadeClassifier.return_value = _make_face_cascade(face_x=1200, face_w=60)

    with patch.dict(sys.modules, {"cv2": cv2_mock}):
        result = SpeakerDetectionService(sample_every_n_frames=1).detect(
            Path("/tmp/fake.mp4"), 0.0, 5.0
        )

    assert result.crop_x + result.crop_w <= 1280
    assert result.crop_x >= 0
