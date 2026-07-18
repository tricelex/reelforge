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


@pytest.fixture(autouse=True)
def _mock_curated_font_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'server.apps.rendering.clip_stages.fonts.curated_font_family',
        lambda slug: 'Montserrat',
    )


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
    sc.watermark_font = 'MONTSERRAT_BOLD'
    sc.watermark_font_asset = None
    sc.watermark_color = '#FFFFFF'
    sc.hook_text = 'Hook!'
    sc.hook_style = 'OVERLAY_TOP'
    sc.hook_enabled = hook_enabled
    sc.hook_font = 'MONTSERRAT_BOLD'
    sc.hook_font_asset = None
    sc.hook_animation = 'NONE'
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
    sc.caption_font = 'MONTSERRAT_BOLD'
    sc.caption_font_asset = None
    sc.caption_animation = 'NONE'
    sc.caption_uppercase = False
    sc.caption_highlight_color = '#FFD400'
    sc.caption_size = 52
    sc.caption_color = '#FFFFFF'
    sc.caption_stroke_color = '#000000'
    sc.caption_stroke_width = 3
    sc.emoji_keyword_map = {}
    sc.intro_transition = 'NONE'
    sc.intro_transition_duration_sec = 0.5
    sc.intro_transition_asset = None
    sc.outro_transition = 'NONE'
    sc.outro_transition_duration_sec = 0.5
    sc.outro_transition_asset = None
    return sc


def _text_overlay(**kwargs: object) -> MagicMock:
    overlay = MagicMock()
    overlay.overlay_type = 'TEXT'
    overlay.text = 'Hello'
    overlay.font = 'MONTSERRAT_BOLD'
    overlay.font_asset = None
    overlay.animation = 'NONE'
    overlay.font_size = 40
    overlay.color = '#FFFFFF'
    overlay.opacity = 1.0
    overlay.x = 0
    overlay.y = 100
    overlay.start_sec = 0.0
    overlay.end_sec = 2.0
    for key, value in kwargs.items():
        setattr(overlay, key, value)
    return overlay


# --- WatermarkStage ---


def test_watermark_stage_skips_when_disabled() -> None:
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=None)
    assert stage.should_run() is False


def test_watermark_stage_runs_when_enabled() -> None:
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is True
    assert stage.order == 7
    assert stage.name == 'watermark'


@patch('server.apps.rendering.clip_stages.watermark.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_text_cmd(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'drawtext' in ' '.join(cmd)


def test_watermark_position_center_coords() -> None:
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    x, y = stage._position_coords('CENTER')
    assert x == '(w-w)/2'
    assert y == '(h-h)/2'


@patch('server.apps.rendering.clip_stages.watermark.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_tiled_position_emits_grid(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(watermark_enabled=True)
    sc.watermark_position = 'TILED'
    sc.watermark_size = 100
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert joined.count('drawtext=') > 1


# --- HookStage ---


def test_hook_stage_skips_no_text() -> None:
    sc = _sc(hook_enabled=True)
    stage = HookStage(
        hook_text='',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    assert stage.should_run() is False


def test_hook_stage_runs_with_text() -> None:
    sc = _sc(hook_enabled=True)
    stage = HookStage(
        hook_text='Amazing hook',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    assert stage.should_run() is True
    assert stage.order == 4
    assert stage.name == 'hook'


# --- IntroConcatStage / OutroConcatStage ---


def test_intro_concat_stage_skips_no_asset() -> None:
    sc = _sc()
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is False
    assert stage.order == 3
    assert stage.name == 'intro_concat'


def test_outro_concat_stage_skips_no_asset() -> None:
    sc = _sc()
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    assert stage.should_run() is False
    assert stage.order == 10
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
    assert stage.order == 5
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
        fonts_dir=Path('/tmp/fonts'),
    )
    assert stage.should_run() is False


def test_caption_stage_runs_when_enabled() -> None:
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={},
        output_path=Path('/out.mp4'),
        ass_path=Path('/out.ass'),
        style_config=sc,
        fonts_dir=Path('/tmp/fonts'),
    )
    assert stage.should_run() is True
    assert stage.order == 6
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
    assert stage.order == 9
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
    assert stage.order == 11
    assert stage.name == 'music_and_sfx_mix'


def test_music_mix_stage_skips_no_asset() -> None:
    sc = _sc(music_enabled=True)
    sc.music_asset = None
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=60.0,
    )
    assert stage.should_run() is False


def test_music_mix_stage_runs_with_sfx_only_no_music() -> None:
    sfx = MagicMock()
    sfx.sfx_asset.file.read.return_value = b'fake_sfx'
    sfx.start_sec = 3.0
    sfx.volume_db = 0.0
    sc = _sc(music_enabled=False)
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
        timed_sfx=[sfx],
    )
    assert stage.should_run() is True


# --- TimedOverlayStage ---


def test_timed_overlay_stage_skips_no_overlays() -> None:
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[],
    )
    assert stage.should_run() is False
    assert stage.order == 8
    assert stage.name == 'timed_overlays'


def test_timed_overlay_stage_runs_with_overlays() -> None:
    overlay = _text_overlay(start_sec=1.0, end_sec=3.0)
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    assert stage.should_run() is True


def test_timed_overlay_returns_input_when_no_text() -> None:
    overlay = _text_overlay(text='')
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    assert stage.should_run() is True
    result = stage.run(Path('/in.mp4'))
    assert result == Path('/in.mp4')


@patch('server.apps.rendering.clip_stages.fonts.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_run_text_ffmpeg(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    overlay = _text_overlay()
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'drawtext' in ' '.join(cmd)


# --- ASSGenerator edge cases ---


def test_ass_color_invalid_hex_returns_white() -> None:
    sc = _sc()
    gen = ASSGenerator(transcript_json={'segments': []}, style_config=sc)
    assert gen._ass_color('#XYZ') == '&H00FFFFFF'


def test_word_by_word_skips_empty_words() -> None:
    sc = _sc()
    sc.caption_style = 'WORD_BY_WORD'
    transcript = {
        'segments': [
            {
                'words': [
                    {'word': '', 'start': 0.0, 'end': 0.3},
                    {'word': 'Hello', 'start': 0.3, 'end': 0.8},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Hello' in result
    assert 'Dialogue: 0,0:00:00.00' not in result


def test_chunked_skips_all_empty_words() -> None:
    sc = _sc()
    sc.caption_style = 'CHUNKED'
    # First chunk (3 words) is all-empty → triggers the `continue` branch on line 163
    # Second chunk has real word → produces a Dialogue line
    transcript = {
        'segments': [
            {
                'words': [
                    {'word': '', 'start': 0.0, 'end': 0.3},
                    {'word': '  ', 'start': 0.3, 'end': 0.6},
                    {'word': '\t', 'start': 0.6, 'end': 0.9},
                    {'word': 'Real', 'start': 1.0, 'end': 1.5},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Real' in result


@patch('server.apps.rendering.clip_stages.fonts.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_run_ffmpeg_failure(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='error')
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    overlay = _text_overlay()
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        with pytest.raises(RuntimeError, match='TimedOverlayStage'):
            stage.run(Path('/in.mp4'))


# --- HookStage run() paths ---


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_overlay_top_run(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'OVERLAY_TOP'
    stage = HookStage(
        hook_text='Big Hook',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'drawtext' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_overlay_center_run(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'OVERLAY_CENTER'
    stage = HookStage(
        hook_text='Center Hook',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'drawtext' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_overlay_ffmpeg_failure(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='bad')
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'OVERLAY_TOP'
    stage = HookStage(
        hook_text='Fail Hook',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        with pytest.raises(RuntimeError, match='HookStage ffmpeg failed'):
            stage.run(Path('/in.mp4'))


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_title_card_run(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'TITLE_CARD'
    stage = HookStage(
        hook_text='Title!',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    assert mock_run.call_count == 2


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_title_card_first_ffmpeg_failure(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='card err')
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'TITLE_CARD'
    stage = HookStage(
        hook_text='Title!',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        with pytest.raises(RuntimeError, match='HookStage title card failed'):
            stage.run(Path('/in.mp4'))


@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
def test_hook_title_card_concat_failure(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    mock_run.side_effect = [
        MagicMock(returncode=0),
        MagicMock(returncode=1, stderr='concat err'),
    ]
    sc = _sc(hook_enabled=True)
    sc.hook_style = 'TITLE_CARD'
    stage = HookStage(
        hook_text='Title!',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        with pytest.raises(RuntimeError, match='HookStage concat failed'):
            stage.run(Path('/in.mp4'))


# --- IntroConcatStage run() ---


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_intro_concat_run(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    assert mock_run.call_count == 2


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_intro_concat_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='scale fail')
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        with pytest.raises(
            RuntimeError,
            match='IntroConcatStage scale ffmpeg failed',
        ):
            stage.run(Path('/in.mp4'))


# --- OutroConcatStage run() ---


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_outro_concat_run(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    outro_asset = MagicMock()
    outro_asset.file.read.return_value = b'fake_outro_bytes'
    sc = _sc()
    sc.outro_asset = outro_asset
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    assert mock_run.call_count == 2


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_outro_concat_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='scale fail')
    outro_asset = MagicMock()
    outro_asset.file.read.return_value = b'fake_outro_bytes'
    sc = _sc()
    sc.outro_asset = outro_asset
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        with pytest.raises(
            RuntimeError,
            match='OutroConcatStage scale ffmpeg failed',
        ):
            stage.run(Path('/in.mp4'))


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_outro_concat_second_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.side_effect = [
        MagicMock(returncode=0),
        MagicMock(returncode=1, stderr='concat fail'),
    ]
    outro_asset = MagicMock()
    outro_asset.file.read.return_value = b'fake_outro_bytes'
    sc = _sc()
    sc.outro_asset = outro_asset
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        with pytest.raises(
            RuntimeError,
            match='OutroConcatStage concat ffmpeg failed',
        ):
            stage.run(Path('/in.mp4'))


# --- CaptionStage run() ---


@patch('server.apps.rendering.clip_stages.captions.subprocess.run')
def test_caption_stage_run(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={'segments': []},
        output_path=Path('/out.mp4'),
        ass_path=Path('/tmp/out.ass'),
        style_config=sc,
        fonts_dir=Path('/tmp/fonts'),
    )
    with (
        patch('server.apps.rendering.clip_stages.captions.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.captions.Path.write_text'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'subtitles' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.captions.subprocess.run')
def test_caption_stage_run_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='sub fail')
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={'segments': []},
        output_path=Path('/out.mp4'),
        ass_path=Path('/tmp/out.ass'),
        style_config=sc,
        fonts_dir=Path('/tmp/fonts'),
    )
    with (
        patch('server.apps.rendering.clip_stages.captions.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.captions.Path.write_text'),
    ):
        with pytest.raises(RuntimeError, match='CaptionStage ffmpeg failed'):
            stage.run(Path('/in.mp4'))


# --- ProgressBarStage run() ---


@patch('server.apps.rendering.clip_stages.progress_bar.subprocess.run')
def test_progress_bar_run_top(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(progress_bar_enabled=True)
    sc.progress_bar_position = 'TOP'
    sc.progress_bar_color = '#FF0000'
    sc.progress_bar_height = 8
    stage = ProgressBarStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
        width=540,
    )
    with patch('server.apps.rendering.clip_stages.progress_bar.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'color=c=0xFF0000:size=540x8' in fc
    assert 'scale=eval=frame' in fc
    assert '540*t/30.000000' in fc
    assert 'overlay=x=0:y=0' in fc


@patch('server.apps.rendering.clip_stages.progress_bar.subprocess.run')
def test_progress_bar_run_bottom(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(progress_bar_enabled=True)
    sc.progress_bar_position = 'BOTTOM'
    sc.progress_bar_color = '#00FF00'
    sc.progress_bar_height = 4
    stage = ProgressBarStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
        width=540,
    )
    with patch('server.apps.rendering.clip_stages.progress_bar.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'color=c=0x00FF00:size=540x4' in fc
    assert 'scale=eval=frame' in fc
    assert 'overlay=x=0:y=H-h' in fc


@patch('server.apps.rendering.clip_stages.progress_bar.subprocess.run')
def test_progress_bar_run_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='bar fail')
    sc = _sc(progress_bar_enabled=True)
    sc.progress_bar_position = 'TOP'
    sc.progress_bar_color = '#FFFFFF'
    sc.progress_bar_height = 6
    stage = ProgressBarStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
        width=540,
    )
    with patch('server.apps.rendering.clip_stages.progress_bar.Path.mkdir'):
        with pytest.raises(
            RuntimeError,
            match='ProgressBarStage ffmpeg failed',
        ):
            stage.run(Path('/in.mp4'))


# --- MusicMixStage run() ---


@patch('server.apps.rendering.clip_stages.music_mix.subprocess.run')
def test_music_mix_stage_mixes_music_and_sfx(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    music_asset = MagicMock()
    music_asset.file.read.return_value = b'fake_music'
    sfx = MagicMock()
    sfx.sfx_asset.file.read.return_value = b'fake_sfx'
    sfx.start_sec = 3.0
    sfx.volume_db = -3.0
    sc = _sc(music_enabled=True)
    sc.music_asset = music_asset
    sc.music_volume_db = -10.0
    sc.music_fade_in_sec = 0.5
    sc.music_fade_out_sec = 0.5
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
        timed_sfx=[sfx],
    )
    with (
        patch('server.apps.rendering.clip_stages.music_mix.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert 'amix=inputs=3' in joined
    assert 'adelay=3000' in joined


@patch('server.apps.rendering.clip_stages.music_mix.subprocess.run')
def test_music_mix_run(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    music_asset = MagicMock()
    music_asset.file.read.return_value = b'fake_music'
    sc = _sc(music_enabled=True)
    sc.music_asset = music_asset
    sc.music_volume_db = -10.0
    sc.music_fade_in_sec = 0.5
    sc.music_fade_out_sec = 0.5
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
    )
    with (
        patch('server.apps.rendering.clip_stages.music_mix.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert 'amix' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.music_mix.subprocess.run')
def test_music_mix_run_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='mix fail')
    music_asset = MagicMock()
    music_asset.file.read.return_value = b'fake_music'
    sc = _sc(music_enabled=True)
    sc.music_asset = music_asset
    sc.music_volume_db = -10.0
    sc.music_fade_in_sec = 0.5
    sc.music_fade_out_sec = 0.5
    stage = MusicMixStage(
        output_path=Path('/out.mp4'),
        style_config=sc,
        video_duration_sec=30.0,
    )
    with (
        patch('server.apps.rendering.clip_stages.music_mix.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.unlink'),
    ):
        with pytest.raises(RuntimeError, match='MusicMixStage ffmpeg failed'):
            stage.run(Path('/in.mp4'))


# --- WatermarkStage image path and error path ---


@patch('server.apps.rendering.clip_stages.watermark.resolve_drawtext_font')
@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_text_ffmpeg_failure(
    mock_run: MagicMock,
    mock_font: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='fail')
    mock_font.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat Bold')
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        with pytest.raises(RuntimeError, match='WatermarkStage text failed'):
            stage.run(Path('/in.mp4'))


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_image_run(mock_run: MagicMock) -> None:
    from server.apps.clips.logic.constants import WatermarkType

    mock_run.return_value = MagicMock(returncode=0)
    wm_asset = MagicMock()
    wm_asset.file.read.return_value = b'fake_png'
    sc = _sc(watermark_enabled=True)
    sc.watermark_type = WatermarkType.IMAGE
    sc.watermark_image = wm_asset
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.watermark.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.watermark.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    assert '-filter_complex' in cmd


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_image_ffmpeg_failure(mock_run: MagicMock) -> None:
    from server.apps.clips.logic.constants import WatermarkType

    mock_run.return_value = MagicMock(returncode=1, stderr='img fail')
    wm_asset = MagicMock()
    wm_asset.file.read.return_value = b'fake_png'
    sc = _sc(watermark_enabled=True)
    sc.watermark_type = WatermarkType.IMAGE
    sc.watermark_image = wm_asset
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.watermark.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.watermark.Path.unlink'),
    ):
        with pytest.raises(RuntimeError, match='WatermarkStage image failed'):
            stage.run(Path('/in.mp4'))


# --- ASSGenerator remaining branches ---


def test_ass_generator_emoji_accent() -> None:
    sc = _sc()
    sc.caption_style = 'EMOJI_ACCENT'
    sc.emoji_keyword_map = {'hello': '👋'}
    transcript = {
        'segments': [
            {
                'start': 0.0,
                'end': 2.0,
                'text': 'Hello world',
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 1.0},
                    {'word': 'world', 'start': 1.0, 'end': 2.0},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Dialogue:' in result


def test_ass_generator_chunked_no_words_segment() -> None:
    """Segment with no words list falls back to text/time from segment."""
    sc = _sc()
    transcript = {
        'segments': [
            {'start': 0.0, 'end': 3.0, 'text': 'Fallback text'},
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Fallback text' in result


def test_ass_generator_chunked_no_words_no_text_segment() -> None:
    """Segment with no words and no text produces no dialogue."""
    sc = _sc()
    transcript = {
        'segments': [
            {'start': 0.0, 'end': 3.0, 'text': ''},
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Dialogue:' not in result


def test_ass_generator_ass_color_8_char() -> None:
    """_ass_color handles 8-character hex (with alpha)."""
    gen = ASSGenerator(transcript_json={}, style_config=None)
    result = gen._ass_color('#80FF0000')
    assert result.startswith('&H')
    assert len(result) == 10


def test_ass_generator_lower_third_empty_text() -> None:
    """_lower_third skips segments with no text."""
    sc = _sc()
    sc.caption_style = 'LOWER_THIRD'
    transcript = {
        'segments': [
            {'start': 0.0, 'end': 1.0, 'text': ''},
            {'start': 1.0, 'end': 2.0, 'text': 'Not empty'},
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'Not empty' in result
    assert result.count('Dialogue:') == 1


# --- Tasks 13-22: fonts, transitions, overlays, captions ---


@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
def test_hook_uses_fontfile(
    mock_resolve: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat')
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(hook_enabled=True)
    sc.hook_font = 'MONTSERRAT_BOLD'
    sc.hook_font_asset = None
    stage = HookStage(
        hook_text='Hi',
        output_path=Path('/out.mp4'),
        style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert "fontfile='/fonts/Montserrat-Bold.ttf'" in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
@patch('server.apps.rendering.clip_stages.watermark.resolve_drawtext_font')
def test_watermark_text_uses_fontfile(
    mock_resolve: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Poppins-Bold.ttf', 'Poppins')
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(watermark_enabled=True)
    sc.watermark_font = 'POPPINS_BOLD'
    sc.watermark_font_asset = None
    sc.watermark_color = '#00FF00'
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert "fontfile='/fonts/Poppins-Bold.ttf'" in joined
    assert 'fontcolor=#00FF00' in joined


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
@patch('server.apps.rendering.clip_stages.fonts.resolve_drawtext_font')
def test_timed_overlay_text_uses_fontfile(
    mock_resolve: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Oswald-Bold.ttf', 'Oswald')
    mock_run.return_value = MagicMock(returncode=0)
    overlay = _text_overlay(
        font='OSWALD_BOLD',
        start_sec=0.0,
        end_sec=2.0,
    )
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert "fontfile='/fonts/Oswald-Bold.ttf'" in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.captions.subprocess.run')
def test_caption_stage_passes_fontsdir(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={'segments': []},
        output_path=Path('/out.mp4'),
        ass_path=Path('/tmp/out.ass'),
        style_config=sc,
        fonts_dir=Path('/tmp/render1/fonts'),
    )
    with (
        patch('server.apps.rendering.clip_stages.captions.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.captions.Path.write_text'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert "fontsdir='/tmp/render1/fonts'" in ' '.join(cmd)


_XFADE_MAP = {
    'CROSSFADE': 'fade',
    'FADE_BLACK': 'fadeblack',
    'FADE_WHITE': 'fadewhite',
    'SLIDE_LEFT': 'slideleft',
    'SLIDE_RIGHT': 'slideright',
    'SLIDE_UP': 'slideup',
    'SLIDE_DOWN': 'slidedown',
    'WIPE_LEFT': 'wipeleft',
    'WIPE_RIGHT': 'wiperight',
    'ZOOM_IN': 'zoomin',
}


@pytest.mark.parametrize(('style_value', 'xfade_name'), list(_XFADE_MAP.items()))
@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.intro_outro.sync_ffprobe_duration',
    return_value=5.0,
)
def test_intro_concat_xfade_transition(
    mock_probe: MagicMock,
    mock_run: MagicMock,
    style_value: str,
    xfade_name: str,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = style_value
    sc.intro_transition_duration_sec = 0.5
    sc.intro_transition_asset = None
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert f'xfade=transition={xfade_name}' in fc
    assert 'acrossfade' in fc


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.intro_outro.sync_ffprobe_duration',
    return_value=0.6,
)
def test_intro_concat_clamps_transition_duration_to_short_clip(
    mock_probe: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'CROSSFADE'
    sc.intro_transition_duration_sec = 3.0
    sc.intro_transition_asset = None
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'xfade=transition=fade:duration=0.540' in fc


def test_intro_concat_none_transition_uses_fast_concat_path() -> None:
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'NONE'
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run') as mock_run,
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        stage.run(Path('/in.mp4'))
        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            assert '-filter_complex' not in call[0][0]


@pytest.mark.parametrize(('style_value', 'xfade_name'), list(_XFADE_MAP.items()))
@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.intro_outro.sync_ffprobe_duration',
    return_value=5.0,
)
def test_outro_concat_xfade_transition(
    mock_probe: MagicMock,
    mock_run: MagicMock,
    style_value: str,
    xfade_name: str,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    outro_asset = MagicMock()
    outro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.outro_asset = outro_asset
    sc.outro_transition = style_value
    sc.outro_transition_duration_sec = 0.5
    sc.outro_transition_asset = None
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert f'xfade=transition={xfade_name}' in fc
    assert 'acrossfade' in fc


def test_outro_concat_none_transition_uses_fast_concat_path() -> None:
    outro_asset = MagicMock()
    outro_asset.file.read.return_value = b'fake_outro_bytes'
    sc = _sc()
    sc.outro_asset = outro_asset
    sc.outro_transition = 'NONE'
    stage = OutroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run') as mock_run,
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        stage.run(Path('/in.mp4'))
        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            assert '-filter_complex' not in call[0][0]


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_intro_concat_custom_transition_asset(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    transition_asset = MagicMock()
    transition_asset.file.read.return_value = b'fake_transition_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'CUSTOM_ASSET'
    sc.intro_transition_asset = transition_asset
    sc.intro_transition_duration_sec = 0.5
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'blend=all_mode=screen' in fc


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_image_type_renders(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    image_asset = MagicMock()
    image_asset.file.read.return_value = b'fake_png_bytes'
    overlay = MagicMock()
    overlay.overlay_type = 'IMAGE'
    overlay.image_asset = image_asset
    overlay.video_asset = None
    overlay.width = 200
    overlay.opacity = 0.9
    overlay.x = 10
    overlay.y = 20
    overlay.start_sec = 1.0
    overlay.end_sec = 4.0
    overlay.animation = 'NONE'
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.unlink'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'overlay=' in fc
    assert "enable='between(t,1.0,4.0)'" in fc
    assert 'scale=200:-1' in fc


_ANIM_FADE_DURATION = 0.3


def test_animation_alpha_expr_fade() -> None:
    from server.apps.rendering.clip_stages.timed_overlays import (
        _animation_alpha_expr,
    )

    expr = _animation_alpha_expr('FADE', start=1.0, end=4.0)
    assert 'if(lt(t,1.3)' in expr
    assert 'if(lt(t,3.7)' in expr


def test_animation_alpha_expr_none_returns_one() -> None:
    from server.apps.rendering.clip_stages.timed_overlays import (
        _animation_alpha_expr,
    )

    assert _animation_alpha_expr('NONE', start=0.0, end=1.0) == '1'


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_text_fade_animation(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    overlay = _text_overlay(
        start_sec=1.0,
        end_sec=4.0,
        animation='FADE',
    )
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert 'alpha=' in joined


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_video_circle_shape(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    video_asset = MagicMock()
    video_asset.file.read.return_value = b'fake_video_bytes'
    overlay = MagicMock()
    overlay.overlay_type = 'VIDEO'
    overlay.image_asset = None
    overlay.video_asset = video_asset
    overlay.shape = 'CIRCLE'
    overlay.width = 240
    overlay.opacity = 1.0
    overlay.x = 50
    overlay.y = 50
    overlay.start_sec = 0.0
    overlay.end_sec = 5.0
    overlay.animation = 'NONE'
    stage = TimedOverlayStage(
        output_path=Path('/out.mp4'),
        timed_overlays=[overlay],
    )
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.unlink'),
        patch.object(
            stage,
            '_next_tmp_path',
            return_value=str(Path('/out.mp4')),
        ),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'geq=' in fc


def test_ass_generator_fade_animation_adds_fad_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'FADE'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\fad(' in result


def test_ass_generator_pop_animation_adds_transform_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'POP'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\t(' in result


def test_ass_generator_none_animation_adds_no_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'NONE'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\fad(' not in result
    assert '\\t(' not in result


def test_ass_generator_karaoke_highlight_produces_overlapping_dialogues() -> None:
    sc = _sc()
    sc.caption_style = 'KARAOKE_HIGHLIGHT'
    sc.caption_highlight_color = '#FFD400'
    transcript = {
        'segments': [
            {
                'start': 0.0,
                'end': 2.0,
                'text': 'Hello world',
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 1.0},
                    {'word': 'world', 'start': 1.0, 'end': 2.0},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert result.count('Dialogue:') == 2
    assert 'Hello' in result
    assert 'world' in result
    assert '\\c&H' in result


def test_caption_uppercase_transforms_chunked_text() -> None:
    sc = _sc()
    sc.caption_uppercase = True
    transcript = {
        'segments': [
            {
                'start': 0.0,
                'end': 1.0,
                'text': 'hello',
                'words': [{'word': 'hello', 'start': 0.0, 'end': 1.0}],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'HELLO' in result
    assert 'hello' not in result.replace('HELLO', '')
