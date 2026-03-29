from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from reelforge.services.media.render_stages.base import RenderStage
from reelforge.services.media.render_stages.captions import ASSGenerator
from reelforge.services.media.render_stages.captions import CaptionStage
from reelforge.services.media.render_stages.captions import CaptionTranslationStage
from reelforge.services.media.render_stages.hook import HookStage
from reelforge.services.media.render_stages.intro_outro import IntroConcatStage
from reelforge.services.media.render_stages.intro_outro import OutroConcatStage
from reelforge.services.media.render_stages.music_mix import MusicMixStage
from reelforge.services.media.render_stages.progress_bar import ProgressBarStage
from reelforge.services.media.render_stages.timed_overlays import TimedOverlayStage
from reelforge.services.media.render_stages.trim_crop import TrimAndCropStage
from reelforge.services.media.render_stages.watermark import WatermarkStage


def _make_layout_config(render_mode: str, **extra) -> MagicMock:
    from reelforge.clipping.models import ClipLayoutConfig

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
    from reelforge.services.media.speaker_detection import SpeakerCropResult

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
        "reelforge.services.media.render_stages.trim_crop.SpeakerDetectionService.detect",
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
    with patch("reelforge.services.media.render_stages.trim_crop.subprocess.run") as mock_run, \
         patch("reelforge.services.media.render_stages.trim_crop.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        out.write_bytes(b"fake output")  # simulate ffmpeg writing output
        result = stage.run(src)
    assert result == out
    mock_run.assert_called_once()


def test_spatial_stack_command_does_not_double_trim() -> None:
    """The filter_complex already trims via trim=start=:end=; no -ss/-to on output."""
    lc = _make_layout_config(
        "SPATIAL_STACK",
        has_spatial_regions=True,
        stack_ratio=0.5,
        region_a_x=0,
        region_a_y=0,
        region_a_w=540,
        region_a_h=960,
        region_b_x=0,
        region_b_y=480,
        region_b_w=540,
        region_b_h=480,
    )
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=10.0,
        end_sec=40.0,
        output_path=Path("/tmp/out.mp4"),
        layout_config=lc,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    cmd = stage._build_spatial_stack_command(Path("/tmp/src.mp4"))
    assert "-ss" not in cmd
    assert "-to" not in cmd


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
    with patch("reelforge.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("reelforge.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
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
    with patch("reelforge.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("reelforge.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"output")
        stage.run(input_path)
    called_cmd = " ".join(mock_run.call_args[0][0])
    assert "xfade" in called_cmd


def _make_hook_style_config(
    hook_enabled: bool = True,
    hook_text: str = "You won't believe this",
    hook_style: str = "OVERLAY_TOP",
    hook_duration_sec: float = 2.5,
    hook_font: str = "Montserrat-Bold",
    hook_size: int = 60,
    hook_color: str = "#FFFFFF",
    hook_bg_color: str = "#CC000000",
    hook_animation: str = "FADE",
) -> MagicMock:
    sc = MagicMock()
    sc.hook_enabled = hook_enabled
    sc.hook_style = hook_style
    sc.hook_duration_sec = hook_duration_sec
    sc.hook_font = hook_font
    sc.hook_size = hook_size
    sc.hook_color = hook_color
    sc.hook_bg_color = hook_bg_color
    sc.hook_animation = hook_animation
    return sc


def test_hook_stage_skipped_when_disabled(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Some hook",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_enabled=False),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_hook_stage_skipped_when_no_hook_text(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_enabled=True),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_hook_stage_name_and_order(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Test",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.name == "hook"
    assert stage.order == 3


def test_hook_overlay_top_command_uses_drawtext_with_enable(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Watch this",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_style="OVERLAY_TOP"),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.hook.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "lt(t" in cmd or "enable" in cmd


def test_hook_title_card_command_uses_concat(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Amazing Title",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_style="TITLE_CARD"),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.hook.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    assert mock_run.call_count == 2


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


_SAMPLE_TRANSCRIPT = {
    "segments": [
        {
            "id": 0,
            "start": 0.0,
            "end": 3.5,
            "text": "You won't believe this",
            "words": [
                {"word": "You", "start": 0.0, "end": 0.5},
                {"word": "won't", "start": 0.6, "end": 1.1},
                {"word": "believe", "start": 1.2, "end": 2.0},
                {"word": "this", "start": 2.1, "end": 3.5},
            ],
        },
        {
            "id": 1,
            "start": 3.6,
            "end": 6.0,
            "text": "It is incredible",
            "words": [
                {"word": "It", "start": 3.6, "end": 3.9},
                {"word": "is", "start": 4.0, "end": 4.3},
                {"word": "incredible", "start": 4.4, "end": 6.0},
            ],
        },
    ]
}


def test_ass_generator_produces_non_empty_content() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="CHUNKED",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    assert "[Script Info]" in content
    assert "[Events]" in content
    assert "You won't believe this" in content or "You" in content


def test_ass_generator_word_by_word_creates_one_event_per_word() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="WORD_BY_WORD",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    # 4 words in segment 0 + 3 words in segment 1 = 7 Dialogue lines
    dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue_lines) == 7


def test_ass_generator_emoji_accent_injects_emoji() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="EMOJI_ACCENT",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={"incredible": "🔥"},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    assert "🔥" in content


def test_caption_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = False
    stage = CaptionStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        ass_path=tmp_path / "sub.ass",
        style_config=sc,
        fonts_dir=Path("/fonts"),
        video_width=1080,
        video_height=1920,
    )
    assert stage.should_run() is False


def test_caption_stage_skipped_when_no_transcript(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = True
    stage = CaptionStage(
        transcript_json={},
        output_path=tmp_path / "out.mp4",
        ass_path=tmp_path / "sub.ass",
        style_config=sc,
        fonts_dir=Path("/fonts"),
        video_width=1080,
        video_height=1920,
    )
    assert stage.should_run() is False


def test_caption_stage_run_writes_ass_and_calls_ffmpeg(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = True
    sc.caption_style = "CHUNKED"
    sc.caption_font = "Montserrat-Bold"
    sc.caption_size = 52
    sc.caption_color = "#FFFFFF"
    sc.caption_stroke_color = "#000000"
    sc.caption_stroke_width = 3
    sc.caption_bg_color = ""
    sc.caption_position = "BOTTOM"
    sc.caption_animation = "POP"
    sc.emoji_keyword_map = {}
    sc.translated_transcript_json = None

    ass_path = tmp_path / "sub.ass"
    stage = CaptionStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        ass_path=ass_path,
        style_config=sc,
        fonts_dir=tmp_path / "fonts",
        video_width=1080,
        video_height=1920,
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.captions.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    assert ass_path.exists()
    cmd = " ".join(mock_run.call_args[0][0])
    assert "subtitles" in cmd


def test_caption_translation_stage_skipped_when_no_target_language(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_translate_to = ""
    stage = CaptionTranslationStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        style_config=sc,
        channel=None,
    )
    assert stage.should_run() is False


def _make_watermark_config(
    enabled: bool = True,
    wtype: str = "TEXT",
    text: str = "@channel",
    position: str = "BOTTOM_RIGHT",
    opacity: float = 0.6,
    size: int = 32,
) -> MagicMock:
    sc = MagicMock()
    sc.watermark_enabled = enabled
    sc.watermark_type = wtype
    sc.watermark_text = text
    sc.watermark_image = None
    sc.watermark_position = position
    sc.watermark_opacity = opacity
    sc.watermark_size = size
    return sc


def test_watermark_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = _make_watermark_config(enabled=False)
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    assert stage.should_run() is False


def test_watermark_stage_text_command_uses_drawtext(tmp_path: Path) -> None:
    sc = _make_watermark_config(wtype="TEXT", text="@testchan")
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.watermark.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "@testchan" in cmd or "testchan" in cmd


def test_watermark_stage_image_command_uses_overlay(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.watermark_enabled = True
    sc.watermark_type = "IMAGE"
    mock_file = MagicMock()
    mock_file.path = str(tmp_path / "logo.png")
    sc.watermark_image = mock_file
    sc.watermark_position = "TOP_RIGHT"
    sc.watermark_opacity = 0.8
    sc.watermark_size = 64
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.watermark.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "overlay" in cmd


def test_timed_overlay_stage_skipped_when_empty(tmp_path: Path) -> None:
    stage = TimedOverlayStage(output_path=tmp_path / "out.mp4", timed_overlays=[])
    assert stage.should_run() is False


def test_timed_overlay_stage_text_uses_drawtext_with_between(tmp_path: Path) -> None:
    overlay = MagicMock()
    overlay.overlay_type = "TEXT"
    overlay.text = "Subscribe!"
    overlay.start_sec = 5.0
    overlay.end_sec = 10.0
    overlay.position_x = 540
    overlay.position_y = 960
    overlay.opacity = 1.0
    overlay.font_size = 40
    overlay.font_color = "#FFFFFF"
    overlay.image = None
    stage = TimedOverlayStage(output_path=tmp_path / "out.mp4", timed_overlays=[overlay])
    assert stage.should_run() is True
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.timed_overlays.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "between" in cmd


def test_progress_bar_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.progress_bar_enabled = False
    stage = ProgressBarStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_progress_bar_stage_command_uses_drawbox(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.progress_bar_enabled = True
    sc.progress_bar_position = "TOP"
    sc.progress_bar_color = "#FFFFFF"
    sc.progress_bar_height = 6
    stage = ProgressBarStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.progress_bar.ffmpeg.probe") as mock_probe, \
         patch("reelforge.services.media.render_stages.progress_bar.subprocess.run") as mock_run:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawbox" in cmd


def _make_music_config(
    enabled: bool = True,
    volume_db: float = -20.0,
    fade_in: float = 1.0,
    fade_out: float = 1.0,
) -> MagicMock:
    sc = MagicMock()
    sc.music_enabled = enabled
    sc.music_asset = MagicMock()
    sc.music_asset.file.path = "/music/track.mp3"
    sc.music_asset.duration_sec = 120.0
    sc.music_volume_db = volume_db
    sc.music_fade_in_sec = fade_in
    sc.music_fade_out_sec = fade_out
    return sc


def test_music_mix_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = _make_music_config(enabled=False)
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_music_mix_stage_skipped_when_no_music_asset(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.music_enabled = True
    sc.music_asset = None
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_music_mix_stage_name_and_order(tmp_path: Path) -> None:
    stage = MusicMixStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_music_config(),
        video_duration_sec=60.0,
    )
    assert stage.name == "music_mix"
    assert stage.order == 10


def test_music_mix_stage_command_uses_amix(tmp_path: Path) -> None:
    sc = _make_music_config(volume_db=-18.0, fade_in=1.0, fade_out=2.0)
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.music_mix.ffmpeg.probe") as mock_probe, \
         patch("reelforge.services.media.render_stages.music_mix.subprocess.run") as mock_run:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "amix" in cmd
    assert "volume" in cmd or "-18" in cmd


def test_caption_stage_uses_configurable_crf_preset(tmp_path: Path) -> None:
    """CaptionStage forwards crf/preset fields to ffmpeg instead of hardcoding 18/slow."""
    sc = MagicMock()
    sc.caption_enabled = True
    sc.caption_style = "CHUNKED"
    sc.caption_font = "Montserrat-Bold"
    sc.caption_size = 52
    sc.caption_color = "#FFFFFF"
    sc.caption_stroke_color = "#000000"
    sc.caption_stroke_width = 3
    sc.caption_bg_color = ""
    sc.caption_position = "BOTTOM"
    sc.caption_animation = "POP"
    sc.emoji_keyword_map = {}
    sc.translated_transcript_json = None

    stage = CaptionStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        ass_path=tmp_path / "sub.ass",
        style_config=sc,
        fonts_dir=tmp_path / "fonts",
        video_width=1080,
        video_height=1920,
        crf=28,
        preset="ultrafast",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.captions.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = mock_run.call_args[0][0]
    assert "28" in cmd
    assert "ultrafast" in cmd
    assert "18" not in cmd
    assert "slow" not in cmd


def test_watermark_stage_uses_configurable_crf_preset(tmp_path: Path) -> None:
    """WatermarkStage forwards crf/preset fields to ffmpeg instead of hardcoding 18/slow."""
    sc = _make_watermark_config(wtype="TEXT")
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc, crf=23, preset="medium")
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.watermark.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = mock_run.call_args[0][0]
    assert "23" in cmd
    assert "medium" in cmd
    assert "18" not in cmd
    assert "slow" not in cmd


def test_timed_overlay_stage_uses_configurable_crf_preset(tmp_path: Path) -> None:
    """TimedOverlayStage forwards crf/preset fields to ffmpeg instead of hardcoding 18/slow."""
    overlay = MagicMock()
    overlay.overlay_type = "TEXT"
    overlay.text = "hello"
    overlay.start_sec = 1.0
    overlay.end_sec = 3.0
    overlay.position = "TOP_LEFT"
    overlay.font_size = 24
    overlay.font_color = "#FFFFFF"
    overlay.bg_color = ""
    stage = TimedOverlayStage(
        output_path=tmp_path / "out.mp4",
        timed_overlays=[overlay],
        crf=23,
        preset="medium",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.timed_overlays.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = mock_run.call_args[0][0]
    assert "23" in cmd
    assert "medium" in cmd
    assert "18" not in cmd
    assert "slow" not in cmd


def test_progress_bar_stage_uses_configurable_crf_preset(tmp_path: Path) -> None:
    """ProgressBarStage forwards crf/preset fields to ffmpeg instead of hardcoding 18/slow."""
    sc = MagicMock()
    sc.progress_bar_enabled = True
    sc.progress_bar_position = "TOP"
    sc.progress_bar_color = "#FFFFFF"
    sc.progress_bar_height = 6
    stage = ProgressBarStage(
        output_path=tmp_path / "out.mp4",
        style_config=sc,
        video_duration_sec=60.0,
        crf=23,
        preset="medium",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.progress_bar.ffmpeg.probe") as mock_probe, \
         patch("reelforge.services.media.render_stages.progress_bar.subprocess.run") as mock_run:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = mock_run.call_args[0][0]
    assert "23" in cmd
    assert "medium" in cmd
    assert "18" not in cmd
    assert "slow" not in cmd


def test_progress_bar_stage_uses_probed_duration(tmp_path: Path) -> None:
    """ProgressBarStage probes actual input duration, not the constructor arg."""
    sc = MagicMock()
    sc.progress_bar_enabled = True
    sc.progress_bar_position = "TOP"
    sc.progress_bar_color = "#FF0000"
    sc.progress_bar_height = 6
    # Pass 30.0 as constructor arg but probe returns 95.5 (actual assembled video)
    stage = ProgressBarStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=30.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.progress_bar.ffmpeg.probe") as mock_probe, \
         patch("reelforge.services.media.render_stages.progress_bar.subprocess.run") as mock_run:
        mock_probe.return_value = {"format": {"duration": "95.5"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "95.5" in cmd
    assert "30.0" not in cmd


def test_music_mix_stage_uses_probed_duration(tmp_path: Path) -> None:
    """MusicMixStage probes actual input duration for fade-out timing."""
    sc = _make_music_config(volume_db=-20.0, fade_in=1.0, fade_out=3.0)
    sc.music_asset.duration_sec = 200.0  # longer than video so no loop
    # Pass 30.0 as constructor arg but probe returns 95.5 (actual assembled video)
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=30.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("reelforge.services.media.render_stages.music_mix.ffmpeg.probe") as mock_probe, \
         patch("reelforge.services.media.render_stages.music_mix.subprocess.run") as mock_run:
        mock_probe.return_value = {"format": {"duration": "95.5"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    # fade-out start = 95.5 - 3.0 = 92.5
    assert "92.5" in cmd
