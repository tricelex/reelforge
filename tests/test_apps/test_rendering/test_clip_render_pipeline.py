"""Tests for ClipRenderPipeline orchestrator."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_render_pipeline import (
    ClipRenderPipeline,
    GatePausedException,
    PipelineRenderConfig,
    _scale_transcript,
)
from server.apps.rendering.clip_stages.base import RenderStageError


def _make_config(tmp_path: Path) -> PipelineRenderConfig:
    return PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=0.0,
        end_sec=60.0,
        hook_text='Test hook',
        transcript_json={'segments': []},
        layout_config=MagicMock(
            render_mode='CENTER_CROP',
            has_spatial_regions=False,
            has_manual_smart_crop=False,
            manual_crop_x=None,
        ),
        style_config=SimpleNamespace(
            caption_enabled=False,
            caption_translate_to='',
            hook_enabled=False,
            watermark_enabled=False,
            progress_bar_enabled=False,
            music_enabled=False,
            intro_asset=None,
            outro_asset=None,
            music_asset=None,
            playback_speed=1.0,
            caption_font_asset=None,
            hook_font_asset=None,
            watermark_font_asset=None,
            color_filter='NONE',
            brightness=0.0,
            contrast=0.0,
            saturation=0.0,
            lut_asset=None,
        ),
        timed_overlays=[],
        render_id='test-render-id',
    )


def test_build_stages_produces_eleven_stages_in_order(tmp_path: Path) -> None:
    config = PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=0.0,
        end_sec=10.0,
        hook_text='',
        transcript_json={'segments': []},
        layout_config=None,
        style_config=None,
    )
    pipeline = ClipRenderPipeline(config)
    stages = pipeline._build_stages()
    assert [s.order for s in stages] == list(range(1, 12))
    assert [s.name for s in stages] == [
        'trim_and_crop',
        'color_grade',
        'intro_concat',
        'hook',
        'caption_translation',
        'captions',
        'watermark',
        'timed_overlays',
        'progress_bar',
        'outro_concat',
        'music_and_sfx_mix',
    ]


def test_pipeline_render_config_accepts_timed_sfx(tmp_path: Path) -> None:
    sfx = object()
    config = PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=0.0,
        end_sec=10.0,
        hook_text='',
        transcript_json={'segments': []},
        layout_config=None,
        style_config=None,
        timed_sfx=[sfx],  # type: ignore[list-item]
    )
    assert config.timed_sfx == [sfx]


def test_scale_transcript_scales_word_and_segment_timestamps() -> None:
    transcript = {
        'segments': [
            {
                'start': 2.0,
                'end': 4.0,
                'text': 'hi',
                'words': [{'word': 'hi', 'start': 2.0, 'end': 4.0}],
            },
        ],
    }
    scaled = _scale_transcript(transcript, playback_speed=2.0)
    seg = scaled['segments'][0]
    assert seg['start'] == 1.0
    assert seg['end'] == 2.0
    assert seg['words'][0]['start'] == 1.0
    assert seg['words'][0]['end'] == 2.0


def test_scale_transcript_noop_at_default_speed() -> None:
    transcript = {'segments': [{'start': 2.0, 'end': 4.0, 'text': 'hi'}]}
    assert _scale_transcript(transcript, playback_speed=1.0) == transcript


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_pipeline_run_skips_disabled_stages(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    config = _make_config(tmp_path)
    src = tmp_path / 'src.mp4'
    src.write_bytes(b'fake video')

    pipeline = ClipRenderPipeline(config)
    with patch(
        'server.apps.rendering.clip_render_pipeline.shutil.copy2',
    ) as mock_copy:
        with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
            result = pipeline.run()

    assert result == config.output_path
    mock_copy.assert_called_once()


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_pipeline_run_start_from_stage_2_skips_trim(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    config = _make_config(tmp_path)
    src = tmp_path / 'src.mp4'
    src.write_bytes(b'fake video')

    pipeline = ClipRenderPipeline(config)
    with patch('server.apps.rendering.clip_render_pipeline.shutil.copy2'):
        pipeline.run(start_from_stage=2)

    mock_run.assert_not_called()


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_pipeline_gate_raises_on_matching_stage(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    config = _make_config(tmp_path)
    src = tmp_path / 'src.mp4'
    src.write_bytes(b'fake video')

    pipeline = ClipRenderPipeline(config)
    with patch('server.apps.rendering.clip_render_pipeline.shutil.copy2'):
        with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
            with pytest.raises(GatePausedException) as exc_info:
                pipeline.run(pause_after_stages={1})

    assert exc_info.value.stage_order == 1


def test_gate_paused_exception_message() -> None:
    exc = GatePausedException(stage_order=3)
    assert exc.stage_order == 3
    assert '3' in str(exc)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_pipeline_run_stage_wraps_exception_in_render_stage_error(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.side_effect = RuntimeError('ffmpeg not found')
    config = _make_config(tmp_path)
    src = tmp_path / 'src.mp4'
    src.write_bytes(b'fake video')

    pipeline = ClipRenderPipeline(config)
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        with pytest.raises(RenderStageError) as exc_info:
            pipeline.run()

    err = exc_info.value
    assert err.stage_name == 'trim_and_crop'
    assert err.stage_order == 1
    assert isinstance(err.cause, RuntimeError)


@patch('server.apps.rendering.clip_stages.trim_crop.subprocess.run')
def test_pipeline_run_stage_does_not_double_wrap_render_stage_error(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    original_error = RenderStageError('trim_and_crop', 1, ValueError('bad'))
    mock_run.side_effect = original_error
    config = _make_config(tmp_path)
    src = tmp_path / 'src.mp4'
    src.write_bytes(b'fake video')

    pipeline = ClipRenderPipeline(config)
    with patch('server.apps.rendering.clip_stages.trim_crop.Path.mkdir'):
        with pytest.raises(RenderStageError) as exc_info:
            pipeline.run()

    assert exc_info.value is original_error
