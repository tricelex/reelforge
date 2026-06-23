"""CaptionTranslationStage and CaptionStage — stages 4 & 5."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, final, override

from server.apps.clips.logic.constants import CaptionStyle
from server.apps.rendering.clip_stages.base import RenderStage

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


class ASSGenerator:
    """Generates an .ass subtitle file from Whisper transcript JSON."""

    def __init__(
        self,
        transcript_json: dict[str, Any],
        style_config: ClipStyleConfig | None = None,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> None:
        """Initialise with transcript data and optional style config."""
        self.transcript_json = transcript_json
        self.style_config = style_config
        self.video_width = video_width
        self.video_height = video_height

    def generate(self) -> str:
        """Generate the full .ass file content."""
        sc = self.style_config
        style = sc.caption_style if sc else CaptionStyle.CHUNKED
        segments = self.transcript_json.get('segments', [])

        header = self._header()
        dialogues: list[str] = []

        if style == CaptionStyle.WORD_BY_WORD:
            dialogues = self._word_by_word(segments)
        elif style == CaptionStyle.LOWER_THIRD:
            dialogues = self._lower_third(segments)
        elif style == CaptionStyle.EMOJI_ACCENT:
            dialogues = self._chunked(
                segments,
                emoji_map=sc.emoji_keyword_map if sc else {},
            )
        else:  # CHUNKED (default)
            dialogues = self._chunked(segments)

        return header + '\n'.join(dialogues) + '\n'

    def _header(self) -> str:
        sc = self.style_config
        font = sc.caption_font if sc else 'Montserrat-Bold'
        size = sc.caption_size if sc else 52
        color = self._ass_color(sc.caption_color if sc else '#FFFFFF')
        stroke_color = self._ass_color(
            sc.caption_stroke_color if sc else '#000000',
        )
        stroke_w = sc.caption_stroke_width if sc else 3
        return (
            '[Script Info]\n'
            'ScriptType: v4.00+\n'
            f'PlayResX: {self.video_width}\n'
            f'PlayResY: {self.video_height}\n'
            '\n'
            '[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, '
            'BorderStyle, Outline, Shadow, Alignment, MarginV\n'
            f'Style: Default,{font},{size},{color},{stroke_color},'
            f'1,{stroke_w},0,2,80\n'
            '\n'
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, '
            'MarginL, MarginR, MarginV, Effect, Text\n'
        )

    def _ass_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f'{h}:{m:02d}:{s:05.2f}'

    def _ass_color(self, hex_color: str) -> str:
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            return f'&H00{b}{g}{r}'
        if len(hex_color) == 8:
            a = hex_color[0:2]
            r = hex_color[2:4]
            g = hex_color[4:6]
            b = hex_color[6:8]
            return f'&H{a}{b}{g}{r}'
        return '&H00FFFFFF'

    def _dialogue(self, start: float, end: float, text: str) -> str:
        return (
            f'Dialogue: 0,{self._ass_time(start)},{self._ass_time(end)},'
            f'Default,,0,0,0,,{text}'
        )

    def _word_by_word(self, segments: list[dict[str, Any]]) -> list[str]:
        lines = []
        for seg in segments:
            for word in seg.get('words', []):
                w = word.get('word', '').strip()
                s = float(word.get('start', 0))
                e = float(word.get('end', s + 0.3))
                if w:
                    lines.append(self._dialogue(s, e, w))
        return lines

    def _apply_emoji(
        self,
        texts: list[str],
        emoji_map: dict[str, str],
    ) -> list[str]:
        return [w + emoji_map.get(w.lower(), '') for w in texts]

    def _chunked(
        self,
        segments: list[dict[str, Any]],
        chunk_size: int = 3,
        emoji_map: dict[str, str] | None = None,
    ) -> list[str]:
        lines = []
        for seg in segments:
            words = seg.get('words', [])
            if not words:
                start = float(seg.get('start', 0))
                end = float(seg.get('end', start + 1))
                text = seg.get('text', '').strip()
                if text:
                    lines.append(self._dialogue(start, end, text))
                continue
            lines.extend(
                self._chunk_words(words, chunk_size, emoji_map or {}),
            )
        return lines

    def _chunk_words(
        self,
        words: list[dict[str, Any]],
        chunk_size: int,
        emoji_map: dict[str, str],
    ) -> list[str]:
        lines = []
        for i in range(0, len(words), chunk_size):
            chunk = words[i : i + chunk_size]
            texts = [w.get('word', '').strip() for w in chunk]
            if emoji_map:
                texts = self._apply_emoji(texts, emoji_map)
            text = ' '.join(t for t in texts if t)
            if not text:
                continue
            s = float(chunk[0].get('start', 0))
            e = float(chunk[-1].get('end', s + 1))
            lines.append(self._dialogue(s, e, text))
        return lines

    def _lower_third(self, segments: list[dict[str, Any]]) -> list[str]:
        lines = []
        for seg in segments:
            text = seg.get('text', '').strip()
            if not text:
                continue
            s = float(seg.get('start', 0))
            e = float(seg.get('end', s + 1))
            lines.append(self._dialogue(s, e, text))
        return lines


@final
@dataclass
class CaptionTranslationStage(RenderStage):
    """Stage 4: Translate captions (stub — returns input unchanged)."""

    transcript_json: dict[str, Any]
    output_path: Path
    style_config: ClipStyleConfig | None

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'caption_translation'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 4

    @override
    def should_run(self) -> bool:
        """Return True if a translation target language is configured."""
        return self.style_config is not None and bool(
            self.style_config.caption_translate_to,
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Translation stub — returns input path unchanged."""
        return input_path


@final
@dataclass
class CaptionStage(RenderStage):
    """Stage 5: Burn subtitles into the clip."""

    transcript_json: dict[str, Any]
    output_path: Path
    ass_path: Path
    style_config: ClipStyleConfig | None
    video_width: int = 1080
    video_height: int = 1920
    crf: int = 18
    preset: str = 'slow'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'captions'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 5

    @override
    def should_run(self) -> bool:
        """Return True if captions are enabled in style config."""
        sc = self.style_config
        return sc is not None and sc.caption_enabled

    @override
    def run(self, input_path: Path) -> Path:
        """Generate .ass file and burn into video."""
        sc = self.style_config
        assert sc is not None  # noqa: S101

        gen = ASSGenerator(
            transcript_json=self.transcript_json,
            style_config=sc,
            video_width=self.video_width,
            video_height=self.video_height,
        )
        ass_content = gen.generate()
        self.ass_path.parent.mkdir(parents=True, exist_ok=True)
        self.ass_path.write_text(ass_content, encoding='utf-8')
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        ass_str = str(self.ass_path).replace("'", "\\'").replace(':', '\\:')
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-vf',
            f"subtitles='{ass_str}'",
            '-c:v',
            'libx264',
            '-crf',
            str(self.crf),
            '-preset',
            self.preset,
            '-c:a',
            'copy',
            str(self.output_path),
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'CaptionStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path
