from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_merge_transcript_with_diarization_assigns_speaker():
    from reelforge.clipping.analysis_helpers import merge_transcript_with_diarization

    transcript_json = {
        "segments": [
            {
                "words": [
                    {"word": "Hello", "start": 0.1, "end": 0.5, "probability": 0.99},
                    {"word": "world", "start": 0.6, "end": 1.0, "probability": 0.98},
                ]
            }
        ]
    }
    diarization = {
        "segments": [
            {"speaker_id": "SPEAKER_00", "start": 0.0, "end": 2.0}
        ]
    }
    result = merge_transcript_with_diarization(transcript_json, diarization)

    assert len(result) == 2
    assert result[0]["word"] == "Hello"
    assert result[0]["speaker_id"] == "SPEAKER_00"
    assert result[1]["speaker_id"] == "SPEAKER_00"


def test_merge_transcript_unknown_speaker_outside_segments():
    from reelforge.clipping.analysis_helpers import merge_transcript_with_diarization

    transcript_json = {
        "segments": [
            {"words": [{"word": "Hi", "start": 10.0, "end": 10.5, "probability": 0.9}]}
        ]
    }
    diarization = {"segments": [{"speaker_id": "SPEAKER_00", "start": 0.0, "end": 5.0}]}
    result = merge_transcript_with_diarization(transcript_json, diarization)
    assert result[0]["speaker_id"] == "UNKNOWN"


def test_build_analysis_manifest_schema_version():
    from reelforge.clipping.analysis_helpers import build_analysis_manifest

    manifest = build_analysis_manifest(
        transcript=[{"word": "test", "start": 0.0, "end": 0.5, "confidence": 1.0, "speaker_id": "SPEAKER_00"}],
        diarization={"segments": [{"speaker_id": "SPEAKER_00", "start": 0.0, "end": 10.0}]},
        face_mappings={},
        scene_cuts=[0.0, 5.0],
        candidates=[],
    )
    assert manifest["schema_version"] == "2.0"
    assert "transcript" in manifest
    assert "speakers" in manifest
    assert "scene_cuts" in manifest
    assert manifest["scene_cuts"] == [0.0, 5.0]


def test_run_scene_detection_returns_list(tmp_path):
    with patch("scenedetect.detect") as mock_detect:
        mock_scene = MagicMock()
        mock_scene.__getitem__ = MagicMock(side_effect=lambda i: MagicMock(get_seconds=lambda: 5.0) if i == 0 else None)
        mock_detect.return_value = [mock_scene]
        from reelforge.clipping.analysis_helpers import run_scene_detection

        result = run_scene_detection("fake.mp4")
        assert isinstance(result, list)
