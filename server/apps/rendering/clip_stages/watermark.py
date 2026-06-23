"""WatermarkStage — stage 6: apply text or image watermark."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.clips.logic.constants import WatermarkType
from server.apps.rendering.clip_stages.base import RenderStage

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class WatermarkStage(RenderStage):
    """Stage 6: Apply watermark (text or image) to the clip."""

    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = 'slow'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'watermark'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 6

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
            'TOP_RIGHT': ('W-w-20', '20'),
            'BOTTOM_LEFT': ('20', 'H-h-20'),
            'BOTTOM_RIGHT': ('W-w-20', 'H-h-20'),
        }
        return positions.get(position, ('W-w-20', 'H-h-20'))

    def _text_watermark(self, input_path: Path, sc: ClipStyleConfig) -> Path:
        x, y = self._position_coords(sc.watermark_position)
        safe_text = sc.watermark_text.replace("'", "\\'").replace(':', '\\:')
        # ClipStyleConfig has no watermark_color; fall back to caption_color
        color = sc.caption_color
        drawtext = (
            f"drawtext=text='{safe_text}'"
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
                f'WatermarkStage text failed: {result.stderr}',
            )
        return self.output_path

    def _image_watermark(
        self,
        input_path: Path,
        sc: ClipStyleConfig,
    ) -> Path:
        wm_bytes: bytes = sc.watermark_image.file.read()  # type: ignore[union-attr]
        x, y = self._position_coords(sc.watermark_position)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            wm_path = tmp.name
        Path(wm_path).write_bytes(wm_bytes)

        overlay = (
            f'[1:v]scale={sc.watermark_size}:-1,'
            f'format=rgba,colorchannelmixer=aa={sc.watermark_opacity}[wm];'
            f'[0:v][wm]overlay={x}:{y}'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-i',
            wm_path,
            '-filter_complex',
            overlay,
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
        Path(wm_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f'WatermarkStage image failed: {result.stderr}',
            )
        return self.output_path
