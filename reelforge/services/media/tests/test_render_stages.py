from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.services.media.render_stages.base import RenderStage
from ***REMOVED***.services.media.render_stages.trim_crop import TrimAndCropStage


def _make_layout_config(render_mode: str, **extra) -> MagicMock:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    lc = MagicMock(spec=ClipLayoutConfig)
    lc.render_mode = render_mode
    lc.has_manual_smart_crop = False
    lc.has_spatial_regions = False
    for k, v in extra.items():
        setattr(lc, k, v)
    return lc


def test_render_stage_is_abstract() -> None:
    """RenderStage cannot be instantiated directly."""
    with pytest.raises(TypeError):
        RenderStage()  # type: ignore[abstract]


def test_trim_and_crop_stage_name_and_order() -> None:
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path("/tmp/stage01.mp4"),
        layout_config=None,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.name == "trim_and_crop"
    assert stage.order == 1


def test_trim_and_crop_center_crop_command() -> None:
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=10.0,
        end_sec=70.0,
        output_path=Path("/tmp/out.mp4"),
        layout_config=_make_layout_config("CENTER_CROP"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    cmd = stage._build_command(Path("/tmp/src.mp4"))
    assert "ffmpeg" in cmd
    assert "-ss" in cmd
    assert "10.0" in cmd
    assert "-to" in cmd
    assert "70.0" in cmd
    assert "ih*9/16:ih" in " ".join(cmd)
    assert "libx264" in cmd


def test_trim_and_crop_smart_crop_auto_detects_speaker() -> None:
    from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult

    lc = _make_layout_config("SMART_CROP", has_manual_smart_crop=False)
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path("/tmp/out.mp4"),
        layout_config=lc,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    mock_result = SpeakerCropResult(crop_x=100, crop_w=405, crop_h=720, confidence=0.8, face_detected=True)
    with patch(
        "***REMOVED***.services.media.render_stages.trim_crop.SpeakerDetectionService.detect",
        return_value=mock_result,
    ):
        cmd = stage._build_command(Path("/tmp/src.mp4"))
    assert "crop=405:720:100:0" in " ".join(cmd)
    assert stage.last_speaker_crop_result is mock_result


def test_trim_and_crop_run_calls_subprocess(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    out = tmp_path / "out.mp4"

    stage = TrimAndCropStage(
        source_path=src,
        start_sec=0.0,
        end_sec=60.0,
        output_path=out,
        layout_config=None,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    with patch("***REMOVED***.services.media.render_stages.trim_crop.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.trim_crop.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        out.write_bytes(b"fake output")  # simulate ffmpeg writing output
        result = stage.run(src)
    assert result == out
    mock_run.assert_called_once()
