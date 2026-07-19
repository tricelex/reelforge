"""Tests for ClipRenderPipeline orchestrator."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_render_pipeline import (
    ClipRenderPipeline,
    GatePausedException,
    PipelineRenderConfig,
    _rebase_transcript,
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


def test_rebase_transcript_shifts_segment_and_word_timestamps() -> None:
    transcript = {
        'segments': [
            {
                'start': 12.0,
                'end': 14.0,
                'text': 'hello world',
                'words': [
                    {'word': 'hello', 'start': 12.0, 'end': 12.5},
                    {'word': 'world', 'start': 12.5, 'end': 14.0},
                ],
            },
        ],
    }
    rebased = _rebase_transcript(
        transcript,
        start_sec=10.0,
        end_sec=20.0,
    )
    seg = rebased['segments'][0]
    assert seg['start'] == 2.0
    assert seg['end'] == 4.0
    assert seg['words'][0]['start'] == 2.0
    assert seg['words'][0]['end'] == 2.5
    assert seg['words'][1]['start'] == 2.5
    assert seg['words'][1]['end'] == 4.0


def test_rebase_transcript_drops_segments_outside_clip_window() -> None:
    transcript = {
        'segments': [
            {'start': 1.0, 'end': 3.0, 'text': 'before'},
            {'start': 12.0, 'end': 14.0, 'text': 'inside'},
            {'start': 25.0, 'end': 27.0, 'text': 'after'},
        ],
    }
    rebased = _rebase_transcript(
        transcript,
        start_sec=10.0,
        end_sec=20.0,
    )
    assert len(rebased['segments']) == 1
    assert rebased['segments'][0]['text'] == 'inside'
    assert rebased['segments'][0]['start'] == 2.0


def test_rebase_transcript_clamps_straddling_segment() -> None:
    transcript = {
        'segments': [
            {
                'start': 9.5,
                'end': 11.0,
                'text': 'edge',
                'words': [
                    {'word': 'before', 'start': 9.5, 'end': 9.9},
                    {'word': 'edge', 'start': 9.9, 'end': 11.0},
                ],
            },
        ],
    }
    rebased = _rebase_transcript(
        transcript,
        start_sec=10.0,
        end_sec=20.0,
    )
    seg = rebased['segments'][0]
    assert seg['start'] == 0.0
    assert seg['end'] == 1.0
    assert len(seg['words']) == 1
    assert seg['words'][0]['word'] == 'edge'
    assert seg['words'][0]['start'] == 0.0
    assert seg['words'][0]['end'] == 1.0


def test_rebase_transcript_rebases_scribe_top_level_words() -> None:
    transcript = {
        'words': [
            {'type': 'word', 'text': 'early', 'start': 1.0, 'end': 2.0},
            {'type': 'word', 'text': 'kept', 'start': 12.0, 'end': 13.0},
            {'type': 'word', 'text': 'late', 'start': 30.0, 'end': 31.0},
        ],
    }
    rebased = _rebase_transcript(
        transcript,
        start_sec=10.0,
        end_sec=20.0,
    )
    assert len(rebased['words']) == 1
    assert rebased['words'][0]['text'] == 'kept'
    assert rebased['words'][0]['start'] == 2.0
    assert rebased['words'][0]['end'] == 3.0


def test_rebase_then_scale_applies_relative_speed() -> None:
    transcript = {
        'segments': [
            {
                'start': 12.0,
                'end': 14.0,
                'text': 'hi',
                'words': [{'word': 'hi', 'start': 12.0, 'end': 14.0}],
            },
        ],
    }
    rebased = _rebase_transcript(
        transcript,
        start_sec=10.0,
        end_sec=20.0,
    )
    scaled = _scale_transcript(rebased, playback_speed=2.0)
    seg = scaled['segments'][0]
    assert seg['start'] == 1.0
    assert seg['end'] == 2.0
    assert seg['words'][0]['start'] == 1.0
    assert seg['words'][0]['end'] == 2.0


def test_build_stages_passes_rebased_transcript_to_caption_stage(
    tmp_path: Path,
) -> None:
    config = PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=10.0,
        end_sec=20.0,
        hook_text='',
        transcript_json={
            'segments': [
                {
                    'start': 12.0,
                    'end': 14.0,
                    'text': 'hi',
                    'words': [{'word': 'hi', 'start': 12.0, 'end': 14.0}],
                },
            ],
        },
        layout_config=None,
        style_config=None,
    )
    stages = ClipRenderPipeline(config)._build_stages()
    caption_stage = next(s for s in stages if s.name == 'captions')
    seg = caption_stage.transcript_json['segments'][0]
    assert seg['start'] == 2.0
    assert seg['end'] == 4.0
    assert seg['words'][0]['start'] == 2.0


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
    # Only stage 1 runs, so the last copy moves its output into place.
    # (Earlier calls may be font cache copies when /tmp is cold.)
    final_call = mock_copy.call_args_list[-1]
    assert final_call.args[-1] == str(config.output_path)
    assert '01_trim_crop.mp4' in str(final_call.args[0])


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
