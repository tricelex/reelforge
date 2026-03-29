from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.services.media.render_stages.base import RenderStage
from ***REMOVED***.services.media.render_stages.intro_outro import IntroConcatStage
from ***REMOVED***.services.media.render_stages.intro_outro import OutroConcatStage
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


def _make_style_config(
    intro_asset=None,
    outro_asset=None,
    intro_transition="NONE",
    outro_transition="NONE",
    transition_duration_sec=0.5,
) -> MagicMock:
    sc = MagicMock()
    sc.intro_asset = intro_asset
    sc.outro_asset = outro_asset
    sc.intro_transition = intro_transition
    sc.outro_transition = outro_transition
    sc.transition_duration_sec = transition_duration_sec
    return sc


def test_intro_concat_skipped_when_no_intro_asset(tmp_path: Path) -> None:
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=None),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_intro_concat_runs_when_intro_asset_set(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    mock_asset.file.path = str(tmp_path / "intro.mp4")
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=mock_asset, intro_transition="NONE"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is True


def test_intro_concat_hard_cut_uses_concat_demuxer(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(b"fake")
    mock_asset.file.path = str(intro_path)
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=mock_asset, intro_transition="NONE"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    input_path = tmp_path / "clip.mp4"
    input_path.write_bytes(b"fake clip")
    with patch("***REMOVED***.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"output")
        stage.run(input_path)
    called_cmd = " ".join(mock_run.call_args[0][0])
    assert "concat" in called_cmd.lower() or "-f" in called_cmd


def test_intro_concat_crossfade_uses_xfade(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(b"fake")
    mock_asset.file.path = str(intro_path)
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(
            intro_asset=mock_asset,
            intro_transition="CROSSFADE",
            transition_duration_sec=0.5,
        ),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    input_path = tmp_path / "clip.mp4"
    input_path.write_bytes(b"fake clip")
    with patch("***REMOVED***.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"output")
        stage.run(input_path)
    called_cmd = " ".join(mock_run.call_args[0][0])
    assert "xfade" in called_cmd


def test_outro_concat_skipped_when_no_outro_asset(tmp_path: Path) -> None:
    stage = OutroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(outro_asset=None),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is False
