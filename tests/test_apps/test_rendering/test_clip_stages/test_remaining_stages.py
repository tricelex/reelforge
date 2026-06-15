"""Tests for all remaining render stages (stages 2-10 except TrimAndCropStage)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.captions import (
    ASSGenerator,
    CaptionStage,
    CaptionTranslationStage,
)
from server.apps.rendering.clip_stages.hook import HookStage
from server.apps.rendering.clip_stages.intro_outro import (
    IntroConcatStage,
    OutroConcatStage,
)
from server.apps.rendering.clip_stages.music_mix import MusicMixStage
from server.apps.rendering.clip_stages.progress_bar import ProgressBarStage
from server.apps.rendering.clip_stages.timed_overlays import TimedOverlayStage
from server.apps.rendering.clip_stages.watermark import WatermarkStage


def _sc(
    watermark_enabled: bool = False,
    hook_enabled: bool = True,
    progress_bar_enabled: bool = False,
    music_enabled: bool = False,
    caption_enabled: bool = True,
    caption_translate_to: str = '',
) -> MagicMock:
    sc = MagicMock()
    sc.watermark_enabled = watermark_enabled
    sc.hook_enabled = hook_enabled
    sc.progress_bar_enabled = progress_bar_enabled
    sc.music_enabled = music_enabled
    sc.music_asset = None
    sc.intro_asset = None
    sc.outro_asset = None
    sc.watermark_type = 'TEXT'
    sc.watermark_text = 'Test'
    sc.watermark_position = 'BOTTOM_RIGHT'
    sc.watermark_opacity = 0.6
    sc.watermark_size = 32
    sc.watermark_image = None
    sc.hook_text = 'Hook!'
    sc.hook_style = 'OVERLAY_TOP'
    sc.hook_enabled = hook_enabled
    sc.hook_duration_sec = 2.5
    sc.hook_size = 60
    sc.hook_color = '#FFFFFF'
    sc.hook_bg_color = '#CC000000'
    sc.progress_bar_position = 'TOP'
    sc.progress_bar_color = '#FFFFFF'
    sc.progress_bar_height = 6
    sc.caption_enabled = caption_enabled
    sc.caption_translate_to = caption_translate_to
    sc.caption_style = 'CHUNKED'
    sc.caption_font = 'Montserrat-Bold'
    sc.caption_size = 52
    sc.caption_color = '#FFFFFF'
    sc.caption_stroke_color = '#000000'
    sc.caption_stroke_width = 3
    sc.emoji_keyword_map = {}
    return sc


# --- WatermarkStage ---

def test_watermark_stage_skips_when_disabled() -> None:
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=None)
    assert stage.should_run() is False


def test_watermark_stage_runs_when_enabled() -> None:
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is True
    assert stage.order == 6
    assert stage.name == 'watermark'


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_text_cmd(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'drawtext' in ' '.join(cmd)


# --- HookStage ---

def test_hook_stage_skips_no_text() -> None:
    sc = _sc(hook_enabled=True)
    stage = HookStage(
        hook_text='', output_path=Path('/out.mp4'), style_config=sc,
    )
    assert stage.should_run() is False


def test_hook_stage_runs_with_text() -> None:
    sc = _sc(hook_enabled=True)
    stage = HookStage(
        hook_text='Amazing hook', output_path=Path('/out.mp4'), style_config=sc,
    )
    assert stage.should_run() is True
    assert stage.order == 3
    assert stage.name == 'hook'


# --- IntroConcatStage / OutroConcatStage ---

def test_intro_concat_stage_skips_no_asset() -> None:
    sc = _sc()
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is False
    assert stage.order == 2
    assert stage.name == 'intro_concat'


def test_outro_concat_stage_skips_no_asset() -> None:
    sc = _sc()
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is False
    assert stage.order == 9
    assert stage.name == 'outro_concat'


# --- CaptionTranslationStage ---

def test_caption_translation_skips_no_target() -> None:
    sc = _sc(caption_translate_to='')
    stage = CaptionTranslationStage(
        transcript_json={},
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    assert stage.should_run() is False
    assert stage.order == 4
    assert stage.name == 'caption_translation'


def test_caption_translation_runs_when_target_set() -> None:
    sc = _sc(caption_translate_to='es')
    stage = CaptionTranslationStage(
        transcript_json={},
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    assert stage.should_run() is True
    result = stage.run(Path('/in.mp4'))
    assert result == Path('/in.mp4')


# --- CaptionStage ---

def test_caption_stage_skips_when_disabled() -> None:
    sc = _sc(caption_enabled=False)
    stage = CaptionStage(
        transcript_json={},
        output_path=Path('/out.mp4'),
        ass_path=Path('/out.ass'),
        style_config=sc,
    )
    assert stage.should_run() is False


def test_caption_stage_runs_when_enabled() -> None:
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={},
        output_path=Path('/out.mp4'),
        ass_path=Path('/out.ass'),
        style_config=sc,
    )
    assert stage.should_run() is True
    assert stage.order == 5
    assert stage.name == 'captions'


# --- ASSGenerator ---

def test_ass_generator_produces_header() -> None:
    sc = _sc()
    gen = ASSGenerator(transcript_json={'segments': []}, style_config=sc)
    result = gen.generate()
    assert '[Script Info]' in result
    assert '[Events]' in result


def test_ass_generator_chunked_produces_dialogues() -> None:
    sc = _sc()
    transcript = {
        'segments': [
            {
                'start': 0.0,
                'end': 3.0,
                'text': 'Hello world test',
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 0.5},
                    {'word': 'world', 'start': 0.5, 'end': 1.0},
                    {'word': 'test', 'start': 1.0, 'end': 1.5},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Dialogue:' in result


def test_ass_generator_word_by_word() -> None:
    sc = _sc()
    sc.caption_style = 'WORD_BY_WORD'
    transcript = {
        'segments': [
            {
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 0.5},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Hello' in result


def test_ass_generator_lower_third() -> None:
    sc = _sc()
    sc.caption_style = 'LOWER_THIRD'
    transcript = {
        'segments': [
            {'start': 0.0, 'end': 3.0, 'text': 'Full sentence here'},
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Full sentence here' in result


# --- ProgressBarStage ---

def test_progress_bar_stage_skips_when_disabled() -> None:
    sc = _sc(progress_bar_enabled=False)
    stage = ProgressBarStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=60.0,
    )
    assert stage.should_run() is False
    assert stage.order == 8
    assert stage.name == 'progress_bar'


# --- MusicMixStage ---

def test_music_mix_stage_skips_when_disabled() -> None:
    sc = _sc(music_enabled=False)
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=60.0,
    )
    assert stage.should_run() is False
    assert stage.order == 10
    assert stage.name == 'music_mix'


def test_music_mix_stage_skips_no_asset() -> None:
    sc = _sc(music_enabled=True)
    sc.music_asset = None
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=60.0,
    )
    assert stage.should_run() is False


# --- TimedOverlayStage ---

def test_timed_overlay_stage_skips_no_overlays() -> None:
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'), timed_overlays=[],
    )
    assert stage.should_run() is False
    assert stage.order == 7
    assert stage.name == 'timed_overlays'


def test_timed_overlay_stage_runs_with_overlays() -> None:
    overlay = MagicMock()
    overlay.text = 'Hello'
    overlay.font_size = 40
    overlay.color = '#FFFFFF'
    overlay.opacity = 1.0
    overlay.x = 0
    overlay.y = 100
    overlay.start_sec = 1.0
    overlay.end_sec = 3.0
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'), timed_overlays=[overlay],
    )
    assert stage.should_run() is True


def test_timed_overlay_returns_input_when_no_text() -> None:
    overlay = MagicMock()
    overlay.text = ''
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'), timed_overlays=[overlay],
    )
    assert stage.should_run() is True
    result = stage.run(Path('/in.mp4'))
    assert result == Path('/in.mp4')
