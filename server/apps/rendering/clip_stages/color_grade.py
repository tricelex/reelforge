"""ColorGradeStage — preset filters, manual adjustments, and custom LUTs."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('***REMOVED***.rendering.clip_stages')

# preset -> (brightness_delta, contrast_delta, saturation_delta)
_PRESET_EQ: dict[str, tuple[float, float, float]] = {
    'NONE': (0.0, 1.0, 1.0),
    'VIVID': (0.02, 1.15, 1.4),
    'MOODY': (-0.05, 1.1, 0.8),
    'WARM': (0.03, 1.05, 1.1),
    'COOL': (-0.02, 1.05, 0.95),
    'BLACK_WHITE': (0.0, 1.1, 0.0),
    'VINTAGE': (-0.03, 0.9, 0.7),
}


@final
@dataclass
class ColorGradeStage(RenderStage):
    """Apply a color-filter preset, manual adjustments, and/or a custom LUT."""

    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        return 'color_grade'

    @property
    @override
    def order(self) -> int:
        return 2

    @override
    def should_run(self) -> bool:
        sc = self.style_config
        if sc is None:
            return False
        return bool(
            sc.color_filter != 'NONE'
            or sc.brightness != 0.0
            or sc.contrast != 0.0
            or sc.saturation != 0.0
            or sc.lut_asset is not None,
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.lut_asset is not None:
            vf, cleanup = self._lut_filter(sc)
        else:
            vf, cleanup = self._eq_filter(sc), None

        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-vf',
            vf,
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
        if cleanup:
            Path(cleanup).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f'ColorGradeStage ffmpeg failed: {result.stderr}')
        return self.output_path

    def _eq_filter(self, sc: ClipStyleConfig) -> str:
        base_b, base_c, base_s = _PRESET_EQ.get(sc.color_filter, (0.0, 1.0, 1.0))
        brightness = base_b + sc.brightness
        contrast = base_c + sc.contrast
        saturation = max(0.0, base_s + sc.saturation)
        return (
            f'eq=brightness={brightness:.3f}:'
            f'contrast={contrast:.3f}:saturation={saturation:.3f}'
        )

    def _lut_filter(self, sc: ClipStyleConfig) -> tuple[str, str]:
        lut_bytes: bytes = sc.lut_asset.file.read()
        with tempfile.NamedTemporaryFile(suffix='.cube', delete=False) as tmp:
            lut_path = tmp.name
        Path(lut_path).write_bytes(lut_bytes)
        safe_path = lut_path.replace("'", "\\'").replace(':', '\\:')
        return f"lut3d='{safe_path}'", lut_path
