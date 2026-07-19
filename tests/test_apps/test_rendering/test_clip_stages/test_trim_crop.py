"""Tests for TrimAndCropStage."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage


def _make_layout(render_mode: str) -> MagicMock:
    lc = MagicMock()
    lc.render_mode = render_mode
    lc.fit_mode = 'CROP'
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
    assert "crop='min(iw,ih*1080/1920)':'min(ih,iw*1920/1080)'" in ' '.join(
        cmd,
    )


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
        with pytest.raises(
            RuntimeError,
            match='TrimAndCropStage ffmpeg failed',
        ):
            stage.run(Path('/src.mp4'))


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_spatial_stack_no_regions_falls_back_to_center(
    mock_run: MagicMock,
) -> None:
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
    assert "crop='min(iw,ih*1080/1920)':'min(ih,iw*1920/1080)'" in ' '.join(
        cmd,
    )


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
def test_smart_crop_calls_speaker_detection(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    mock_result = MagicMock(
        crop_x=100,
        crop_y=0,
        crop_w=600,
        crop_h=1000,
    )
    lc = _make_layout('SMART_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    stage._speaker_svc = MagicMock()
    stage._speaker_svc.detect.return_value = mock_result
    with (
        patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'),
        patch(
            'server.apps.rendering.clip_stages.probe.sync_ffprobe_dimensions',
            return_value=(1920, 1080),
        ),
    ):
        result = stage.run(Path('/src.mp4'))
    assert result == Path('/out.mp4')
    assert stage.last_speaker_crop_result is mock_result
    assert stage._speaker_svc.detect.called
    cmd = mock_run.call_args[0][0]
    assert 'crop=600:1000:100:0' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_smart_crop_clamps_oversized_rect(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    mock_result = MagicMock(
        crop_x=0,
        crop_y=0,
        crop_w=1920,
        crop_h=1080,
    )
    lc = _make_layout('SMART_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
        width=960,
        height=540,
    )
    stage._speaker_svc = MagicMock()
    stage._speaker_svc.detect.return_value = mock_result
    with (
        patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'),
        patch(
            'server.apps.rendering.clip_stages.probe.sync_ffprobe_dimensions',
            return_value=(640, 360),
        ),
    ):
        stage.run(Path('/src.mp4'))
    cmd = mock_run.call_args[0][0]
    assert 'crop=640:360:0:0' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_smart_crop_falls_back_when_probe_fails(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    mock_result = MagicMock(
        crop_x=0,
        crop_y=0,
        crop_w=1920,
        crop_h=1080,
    )
    lc = _make_layout('SMART_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
    )
    stage._speaker_svc = MagicMock()
    stage._speaker_svc.detect.return_value = mock_result
    with (
        patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'),
        patch(
            'server.apps.rendering.clip_stages.probe.sync_ffprobe_dimensions',
            return_value=(None, None),
        ),
    ):
        stage.run(Path('/src.mp4'))
    cmd = mock_run.call_args[0][0]
    assert "crop='min(iw,ih*" in ' '.join(cmd)


def test_center_crop_cmd_includes_speed_filters_when_not_default() -> None:
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=None,
        playback_speed=2.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1]
    af_index = cmd.index('-af') if '-af' in cmd else None
    assert 'setpts=0.500000*PTS' in vf
    assert af_index is not None
    assert 'atempo=2.0' in cmd[af_index + 1]


def test_center_crop_cmd_skips_speed_filters_at_default() -> None:
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=None,
        playback_speed=1.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    assert '-af' not in cmd


def test_extreme_speed_chains_multiple_atempo() -> None:
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=None,
        playback_speed=3.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    af_index = cmd.index('-af')
    assert cmd[af_index + 1].count('atempo=') == 2


def test_center_crop_blur_fill_mode() -> None:
    layout = MagicMock()
    layout.render_mode = 'CENTER_CROP'
    layout.fit_mode = 'BLUR_FILL'
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=layout,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = (
        cmd[cmd.index('-vf') + 1]
        if '-vf' in cmd
        else cmd[cmd.index('-filter_complex') + 1]
    )
    assert 'boxblur' in vf
    assert 'overlay' in vf


def test_center_crop_default_fit_mode_unchanged() -> None:
    layout = MagicMock()
    layout.render_mode = 'CENTER_CROP'
    layout.fit_mode = 'CROP'
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=layout,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1]
    assert 'boxblur' not in vf
    assert vf == (
        "crop='min(iw,ih*1080/1920)':'min(ih,iw*1920/1080)',"
        'scale=1080:1920,fps=30'
    )


def test_center_crop_landscape_format() -> None:
    """A 16:9 target keeps the crop expression aspect-aware."""
    layout = MagicMock()
    layout.render_mode = 'CENTER_CROP'
    layout.fit_mode = 'CROP'
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=10.0,
        output_path=Path('/out.mp4'),
        layout_config=layout,
        width=1920,
        height=1080,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1]
    assert vf == (
        "crop='min(iw,ih*1920/1080)':'min(ih,iw*1080/1920)',"
        'scale=1920:1080,fps=30'
    )


def test_smart_crop_passes_target_dimensions() -> None:
    """Smart crop forwards the output dimensions to speaker detection."""
    mock_result = MagicMock(crop_x=0, crop_y=0, crop_w=1920, crop_h=1080)
    lc = _make_layout('SMART_CROP')
    stage = TrimAndCropStage(
        source_path=Path('/src.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path('/out.mp4'),
        layout_config=lc,
        width=1920,
        height=1080,
    )
    stage._speaker_svc = MagicMock()
    stage._speaker_svc.detect.return_value = mock_result
    with patch(
        'server.apps.rendering.clip_stages.probe.sync_ffprobe_dimensions',
        return_value=(1920, 1080),
    ):
        cmd = stage._build_command(Path('/src.mp4'))
    kwargs = stage._speaker_svc.detect.call_args.kwargs
    assert kwargs['target_width'] == 1920
    assert kwargs['target_height'] == 1080
    vf = cmd[cmd.index('-vf') + 1]
    assert vf.startswith('crop=1920:1080:0:0,')
