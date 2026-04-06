from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ***REMOVED***.services.media.speaker_detection import (
    DiarizationSegment,
    SpeakerCropResult,
    SpeakerDetectionService,
)


def test_detect_returns_manual_crop_when_all_fields_set():
    service = SpeakerDetectionService()
    with patch("cv2.VideoCapture") as mock_cap:
        mock_instance = MagicMock()
        mock_instance.get.side_effect = [1920, 1080]  # width, height
        mock_cap.return_value = mock_instance
        result = service.detect(
            video_path="fake.mp4",
            start_sec=0.0,
            end_sec=10.0,
            manual_crop_x=200,
            manual_crop_y=0,
            manual_crop_w=400,
            manual_crop_h=800,
        )
    assert result.face_detected is True
    assert result.confidence == 1.0
    assert result.crop_x == 200
    assert result.crop_w == 400


def test_detect_falls_back_to_center_crop_when_no_face():
    service = SpeakerDetectionService()
    with patch.object(service, "detect_faces_for_segment", return_value=[{"timestamp": 0.5, "faces": []}]):
        with patch("cv2.VideoCapture") as mock_cap:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = [1080, 1920]  # width, height
            mock_cap.return_value = mock_instance
            result = service.detect("fake.mp4", 0.0, 10.0)
    assert result.face_detected is False
    assert result.confidence == 0.0


def test_diarization_segment_dataclass():
    seg = DiarizationSegment(speaker_id="SPEAKER_00", start=0.0, end=5.0)
    assert seg.speaker_id == "SPEAKER_00"
    assert seg.start == 0.0


def test_speaker_crop_result_has_speaker_id():
    result = SpeakerCropResult(
        crop_x=0, crop_w=608, crop_h=1080, confidence=0.8, face_detected=True, speaker_id="SPEAKER_00"
    )
    assert result.speaker_id == "SPEAKER_00"
