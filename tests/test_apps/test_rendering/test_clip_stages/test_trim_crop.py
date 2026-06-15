"""Tests for TrimAndCropStage."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage


def _make_layout(render_mode: str) -> MagicMock:
    lc = MagicMock()
    lc.render_mode = render_mode
    lc.has_manual_smart_crop = False
    lc.manual_crop_x = None
    lc.manual_crop_y = None
    lc.manual_crop_w = None
    lc.manual_crop_h = None
    lc.has_spatial_regions = False
    lc.stack_ratio = 0.6
    return lc


def test_trim_and_crop_order_and_name() -> None:
    lc = _make_layout('CENTER_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    assert stage.order == 1
    assert stage.name == 'trim_and_crop'
    assert stage.should_run() is True


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_center_crop_runs_ffmpeg(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    lc = _make_layout('CENTER_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=10.0,
        end_sec=70.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        result = stage.run(Path('/src.mp4'))
    assert result == Path('/out.mp4')
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert 'crop=ih*9/16:ih' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_ffmpeg_failure_raises_runtime_error(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='error message')
    lc = _make_layout('CENTER_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        with pytest.raises(RuntimeError, match='TrimAndCropStage ffmpeg failed'):
            stage.run(Path('/src.mp4'))


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_spatial_stack_no_regions_falls_back_to_center(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    lc = _make_layout('SPATIAL_STACK')
    lc.has_spatial_regions = False
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        stage.run(Path('/src.mp4'))
    cmd = mock_run.call_args[0][0]
    assert 'crop=ih*9/16:ih' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_spatial_stack_with_regions(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    lc = _make_layout('SPATIAL_STACK')
    lc.has_spatial_regions = True
    lc.region_a_x = 0
    lc.region_a_y = 0
    lc.region_a_w = 1920
    lc.region_a_h = 540
    lc.region_b_x = 0
    lc.region_b_y = 540
    lc.region_b_w = 1920
    lc.region_b_h = 540
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        stage.run(Path('/src.mp4'))
    cmd = mock_run.call_args[0][0]
    assert 'filter_complex' in cmd or 'vstack' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.trim_crop.SpeakerDetectionService',
)
def test_smart_crop_uses_speaker_detection(
    mock_sds_class: MagicMock, mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    mock_result = MagicMock()
    mock_result.crop_x = 200
    mock_result.crop_w = 540
    mock_result.crop_h = 960
    mock_sds_class.return_value.detect.return_value = mock_result
    lc = _make_layout('SMART_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        stage.run(Path('/src.mp4'))
    assert mock_sds_class.return_value.detect.called
    assert stage.last_speaker_crop_result is mock_result
