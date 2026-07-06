from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.color_grade import ColorGradeStage


def _sc(
    color_filter: str = 'NONE',
    brightness: float = 0.0,
    contrast: float = 0.0,
    saturation: float = 0.0,
    lut_asset: object | None = None,
) -> MagicMock:
    sc = MagicMock()
    sc.color_filter = color_filter
    sc.brightness = brightness
    sc.contrast = contrast
    sc.saturation = saturation
    sc.lut_asset = lut_asset
    return sc


def test_should_run_false_when_all_defaults() -> None:
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=_sc())
    assert stage.should_run() is False


def test_should_run_true_when_preset_set() -> None:
    stage = ColorGradeStage(
        output_path=Path('/out.mp4'),
        style_config=_sc(color_filter='VIVID'),
    )
    assert stage.should_run() is True


def test_should_run_true_when_manual_adjustment_set() -> None:
    stage = ColorGradeStage(
        output_path=Path('/out.mp4'),
        style_config=_sc(brightness=0.1),
    )
    assert stage.should_run() is True


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_preset_eq_filter_applied(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(color_filter='VIVID', brightness=0.1, contrast=0.05)
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-vf') + 1]
    assert 'eq=' in fc


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_lut_asset_takes_precedence(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    lut_asset = MagicMock()
    lut_asset.file.read.return_value = b'fake cube data'
    sc = _sc(color_filter='VIVID', lut_asset=lut_asset)
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.color_grade.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.color_grade.Path.unlink'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-vf') + 1]
    assert 'lut3d=' in fc
    assert 'eq=' not in fc


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_color_grade_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='bad filter')
    sc = _sc(color_filter='MOODY')
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'):
        with pytest.raises(RuntimeError, match='ColorGradeStage'):
            stage.run(Path('/in.mp4'))
