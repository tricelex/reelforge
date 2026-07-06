"""WatermarkStage — apply text or image watermark."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.clips.logic.constants import WatermarkType
from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args
from server.apps.rendering.clip_stages.fonts import resolve_drawtext_font

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class WatermarkStage(RenderStage):
    """Apply watermark (text or image) to the clip."""

    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'watermark'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 7

    @override
    def should_run(self) -> bool:
        """Return True if watermark is enabled in style config."""
        return (
            self.style_config is not None
            and self.style_config.watermark_enabled
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Apply watermark to the clip."""
        sc = self.style_config
        assert sc is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.watermark_type == WatermarkType.IMAGE and sc.watermark_image:
            return self._image_watermark(input_path, sc)
        return self._text_watermark(input_path, sc)

    def _position_coords(self, position: str) -> tuple[str, str]:
        """Convert position name to x:y ffmpeg expressions."""
        positions: dict[str, tuple[str, str]] = {
            'TOP_LEFT': ('20', '20'),
            'TOP_RIGHT': ('w-w-20', '20'),
            'BOTTOM_LEFT': ('20', 'h-h-20'),
            'BOTTOM_RIGHT': ('w-w-20', 'h-h-20'),
            'CENTER': ('(w-w)/2', '(h-h)/2'),
        }
        return positions.get(position, ('w-w-20', 'h-h-20'))

    def _tiled_positions(
        self,
        watermark_size: int,
        cols: int = 3,
        rows: int = 5,
    ) -> list[tuple[int, int]]:
        spacing_x = 1080 // cols
        spacing_y = 1920 // rows
        return [
            (c * spacing_x + spacing_x // 4, r * spacing_y + spacing_y // 4)
            for r in range(rows)
            for c in range(cols)
        ]

    def _text_watermark(self, input_path: Path, sc: ClipStyleConfig) -> Path:
        safe_text = sc.watermark_text.replace("'", "\\'").replace(':', '\\:')
        font_path, _family = resolve_drawtext_font(
            sc.watermark_font,
            sc.watermark_font_asset,
        )
        safe_font = font_path.replace("'", "\\'").replace(':', '\\:')
        color = sc.watermark_color

        if sc.watermark_position == 'TILED':
            positions = self._tiled_positions(sc.watermark_size)
            parts = [
                (
                    f"drawtext=text='{safe_text}'"
                    f':fontfile={safe_font}'
                    f':fontsize={sc.watermark_size}'
                    f':fontcolor={color}@{sc.watermark_opacity}'
                    f':x={x}:y={y}'
                )
                for x, y in positions
            ]
            drawtext = ','.join(parts)
        else:
            x, y = self._position_coords(sc.watermark_position)
            drawtext = (
                f"drawtext=text='{safe_text}'"
                f':fontfile={safe_font}'
                f':fontsize={sc.watermark_size}'
                f':fontcolor={color}@{sc.watermark_opacity}'
                f':x={x}:y={y}'
            )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-vf',
            drawtext,
            *clip_filter_encode_args(
                crf=self.crf,
                preset=self.preset,
                fps=self.fps,
                audio_bitrate=self.audio_bitrate,
            ),
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
                f'WatermarkStage text failed: {result.stderr}',
            )
        return self.output_path

    def _image_watermark(
        self,
        input_path: Path,
        sc: ClipStyleConfig,
    ) -> Path:
        wm_bytes: bytes = sc.watermark_image.file.read()  # type: ignore[union-attr]
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            wm_path = tmp.name
        Path(wm_path).write_bytes(wm_bytes)

        if sc.watermark_position == 'TILED':
            positions = self._tiled_positions(sc.watermark_size)
            scale = (
                f'[1:v]scale={sc.watermark_size}:-1,'
                f'format=rgba,colorchannelmixer=aa={sc.watermark_opacity}[wm];'
            )
            overlay_parts = []
            prev = '[0:v]'
            for i, (x, y) in enumerate(positions):
                out_label = f'[v{i}]' if i < len(positions) - 1 else '[out]'
                overlay_parts.append(
                    f'{prev}[wm]overlay={x}:{y}{out_label}',
                )
                prev = out_label
            overlay = scale + ';'.join(overlay_parts)
            map_video = '[out]'
        else:
            x, y = self._position_coords(sc.watermark_position)
            overlay = (
                f'[1:v]scale={sc.watermark_size}:-1,'
                f'format=rgba,colorchannelmixer=aa={sc.watermark_opacity}[wm];'
                f'[0:v][wm]overlay={x}:{y}'
            )
            map_video = None

        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-i',
            wm_path,
            '-filter_complex',
            overlay,
        ]
        if map_video is not None:
            cmd += ['-map', map_video, '-map', '0:a']
        cmd += clip_filter_encode_args(
            crf=self.crf,
            preset=self.preset,
            fps=self.fps,
            audio_bitrate=self.audio_bitrate,
        )
        cmd.append(str(self.output_path))

        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        Path(wm_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f'WatermarkStage image failed: {result.stderr}',
            )
        return self.output_path
