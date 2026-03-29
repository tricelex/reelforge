from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS time format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB or #AARRGGBB hex to ASS &HAABBGGRR format."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    if len(h) == 8:
        a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    return "&H00FFFFFF"


def _chunk_words(words: list[dict[str, Any]], chunk_size: int = 3) -> list[list[dict[str, Any]]]:
    """Group word dicts into chunks of up to chunk_size."""
    return [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]


class ASSGenerator:
    """Generates ASS subtitle file content from a Whisper transcript_json.

    Supports four caption styles: WORD_BY_WORD, CHUNKED, LOWER_THIRD, EMOJI_ACCENT.
    Falls back to segment-level timing when word timestamps are absent.
    """

    def __init__(
        self,
        transcript_json: dict[str, Any],
        caption_style: str,
        caption_font: str,
        caption_size: int,
        caption_color: str,
        caption_stroke_color: str,
        caption_stroke_width: int,
        caption_bg_color: str,
        caption_position: str,
        caption_animation: str,
        emoji_keyword_map: dict[str, str],
        video_width: int,
        video_height: int,
    ) -> None:
        self.transcript = transcript_json
        self.style = caption_style
        self.font = caption_font
        self.size = caption_size
        self.color = _hex_to_ass_color(caption_color)
        self.stroke_color = _hex_to_ass_color(caption_stroke_color)
        self.stroke_width = caption_stroke_width
        self.bg_color = _hex_to_ass_color(caption_bg_color) if caption_bg_color else ""
        self.position = caption_position
        self.animation = caption_animation
        self.emoji_map = emoji_keyword_map
        self.width = video_width
        self.height = video_height

    def _alignment(self) -> int:
        """ASS alignment numpad: 2=bottom-center, 5=middle-center, 8=top-center."""
        return {"TOP": 8, "CENTER": 5, "BOTTOM": 2}.get(self.position, 2)

    def _header(self) -> str:
        alignment = self._alignment()
        bg_line = f"\nBackColour={self.bg_color}" if self.bg_color else ""
        return (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.width}\n"
            f"PlayResY: {self.height}\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{self.font},{self.size},{self.color},"
            f"{self.color},{self.stroke_color},{self.bg_color or '&H00000000'},"
            f"-1,0,0,0,100,100,0,0,1,{self.stroke_width},0,"
            f"{alignment},10,10,30,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    def _dialogue(self, start: float, end: float, text: str) -> str:
        return (
            f"Dialogue: 0,{_seconds_to_ass_time(start)},{_seconds_to_ass_time(end)},"
            f"Default,,0,0,0,,{text}\n"
        )

    def _apply_emoji(self, text: str) -> str:
        for keyword, emoji in self.emoji_map.items():
            if keyword.lower() in text.lower():
                text = text + f" {emoji}"
        return text

    def generate(self) -> str:
        lines = [self._header()]
        segments = self.transcript.get("segments", [])

        for seg in segments:
            words = seg.get("words", [])
            seg_text = seg.get("text", "").strip()
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", seg_start + 1))

            if self.style == "WORD_BY_WORD":
                if words:
                    for w in words:
                        wstart = float(w.get("start", seg_start))
                        wend = float(w.get("end", seg_end))
                        lines.append(self._dialogue(wstart, wend, w.get("word", "").strip()))
                else:
                    lines.append(self._dialogue(seg_start, seg_end, seg_text))

            elif self.style == "LOWER_THIRD":
                lines.append(self._dialogue(seg_start, seg_end, seg_text))

            elif self.style in ("CHUNKED", "EMOJI_ACCENT"):
                if words:
                    for chunk in _chunk_words(words, chunk_size=3):
                        cstart = float(chunk[0].get("start", seg_start))
                        cend = float(chunk[-1].get("end", seg_end))
                        ctext = " ".join(w.get("word", "").strip() for w in chunk)
                        if self.style == "EMOJI_ACCENT":
                            ctext = self._apply_emoji(ctext)
                        lines.append(self._dialogue(cstart, cend, ctext))
                else:
                    text = seg_text
                    if self.style == "EMOJI_ACCENT":
                        text = self._apply_emoji(text)
                    lines.append(self._dialogue(seg_start, seg_end, text))

        return "".join(lines)


@dataclass
class CaptionTranslationStage(RenderStage):
    """Stage 4: Translate transcript_json to target language via LLM.

    Translation is cached in ClipStyleConfig.translated_transcript_json so
    retrying CaptionStage alone doesn't re-translate.
    This stage does NOT modify the video — it returns input_path unchanged
    after updating translated_transcript_json on the style config.
    """

    transcript_json: dict[str, Any]
    output_path: Path
    style_config: ClipStyleConfig | None
    channel: Channel | None

    @property
    def name(self) -> str:
        return "caption_translation"

    @property
    def order(self) -> int:
        return 4

    def should_run(self) -> bool:
        if self.style_config is None:
            return False
        return bool(self.style_config.caption_translate_to)

    def run(self, input_path: Path) -> Path:
        """Translate transcript via LLM. Updates style_config in-place and returns input_path unchanged."""
        import json

        sc = self.style_config

        if sc.translated_transcript_json:
            logger.info("Using cached translation", extra={"style_config_id": str(sc.pk)})
            return input_path

        from ***REMOVED***.services.providers.registry import get_llm_provider

        llm = get_llm_provider(self.channel)
        target_lang = sc.caption_translate_to
        prompt = (
            f"Translate the following Whisper transcript JSON to {target_lang}. "
            "Preserve the exact JSON structure, keys, and timestamps. "
            "Only translate the 'text' and 'word' string values. "
            "Return only valid JSON with no commentary.\n\n"
            f"{self.transcript_json}"
        )
        response = llm.complete(prompt=prompt, system="You are a professional translator.")

        try:
            translated = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON for translation: {exc}") from exc

        sc.__class__.objects.filter(pk=sc.pk).update(translated_transcript_json=translated)
        sc.translated_transcript_json = translated

        logger.info(
            "Caption translation completed",
            extra={"target_lang": target_lang, "style_config_id": str(sc.pk)},
        )
        return input_path


@dataclass
class CaptionStage(RenderStage):
    """Stage 5: Generate ASS subtitle file and burn captions into the video."""

    transcript_json: dict[str, Any]
    output_path: Path
    ass_path: Path
    style_config: ClipStyleConfig | None
    fonts_dir: Path
    video_width: int = 1080
    video_height: int = 1920
    crf: int = 18
    preset: str = "slow"

    @property
    def name(self) -> str:
        return "captions"

    @property
    def order(self) -> int:
        return 5

    def should_run(self) -> bool:
        if self.style_config is None or not self.style_config.caption_enabled:
            return False
        return bool(self.transcript_json)

    def run(self, input_path: Path) -> Path:
        sc = self.style_config

        effective_transcript = sc.translated_transcript_json or self.transcript_json

        gen = ASSGenerator(
            transcript_json=effective_transcript,
            caption_style=sc.caption_style,
            caption_font=sc.caption_font,
            caption_size=sc.caption_size,
            caption_color=sc.caption_color,
            caption_stroke_color=sc.caption_stroke_color,
            caption_stroke_width=sc.caption_stroke_width,
            caption_bg_color=sc.caption_bg_color,
            caption_position=sc.caption_position,
            caption_animation=sc.caption_animation,
            emoji_keyword_map=sc.emoji_keyword_map,
            video_width=self.video_width,
            video_height=self.video_height,
        )
        self.ass_path.parent.mkdir(parents=True, exist_ok=True)
        self.ass_path.write_text(gen.generate(), encoding="utf-8")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        escaped_ass = str(self.ass_path).replace("\\", "/").replace(":", "\\:")
        vf = f"subtitles={escaped_ass}:fontsdir={self.fonts_dir!s}"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            str(self.crf),
            "-preset",
            self.preset,
            "-c:a",
            "copy",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"CaptionStage ffmpeg failed: {result.stderr}")

        logger.info(
            "CaptionStage completed",
            extra={"style": sc.caption_style, "output": str(self.output_path)},
        )
        return self.output_path
