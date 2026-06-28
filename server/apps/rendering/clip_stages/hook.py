"""HookStage — stage 3: overlay or prepend a hook text on the clip."""

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


@final
@dataclass
class HookStage(RenderStage):
    """Stage 3: Overlay or prepend hook text."""

    hook_text: str
    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = 'slow'
    width: int = 1080
    height: int = 1920
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'hook'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 3

    @override
    def should_run(self) -> bool:
        """Return True if hook text and style config are present."""
        return (
            bool(self.hook_text)
            and self.style_config is not None
            and self.style_config.hook_enabled
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Apply hook text to the clip."""
        from server.apps.clips.logic.constants import HookStyle  # noqa: PLC0415

        sc = self.style_config
        assert sc is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.hook_style == HookStyle.TITLE_CARD:
            return self._title_card(input_path, sc)
        return self._overlay(input_path, sc)

    def _overlay(self, input_path: Path, sc: ClipStyleConfig) -> Path:
        """Draw hook text as timed overlay at top or center."""
        from server.apps.clips.logic.constants import HookStyle  # noqa: PLC0415

        y_expr = (
            '(h/2)-(text_h/2)'
            if sc.hook_style == HookStyle.OVERLAY_CENTER
            else '20'
        )
        safe_text = self.hook_text.replace("'", "\\'").replace(':', '\\:')
        drawtext = (
            f"drawtext=text='{safe_text}'"
            f':fontsize={sc.hook_size}'
            f':fontcolor={sc.hook_color}'
            f':x=(w-text_w)/2:y={y_expr}'
            f":enable='between(t,0,{sc.hook_duration_sec})'"
            f':box=1:boxcolor={sc.hook_bg_color}:boxborderw=10'
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
                f'HookStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path

    def _title_card(
        self,
        input_path: Path,
        sc: ClipStyleConfig,
    ) -> Path:
        """Prepend a black title card with the hook text."""
        safe_text = self.hook_text.replace("'", "\\'").replace(':', '\\:')

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            card_path = tmp.name

        # Generate title card
        drawtext = (
            f"drawtext=text='{safe_text}'"
            f':fontsize={sc.hook_size}'
            f':fontcolor={sc.hook_color}'
            f':x=(w-text_w)/2:y=(h-text_h)/2'
        )
        card_cmd = [
            'ffmpeg',
            '-y',
            '-f',
            'lavfi',
            '-i',
            f'color=c=black:s={self.width}x{self.height}:d={sc.hook_duration_sec}',
            '-vf',
            drawtext,
            '-c:v',
            'libx264',
            '-crf',
            str(self.crf),
            '-preset',
            self.preset,
            card_path,
        ]
        r1 = subprocess.run(  # noqa: S603
            card_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if r1.returncode != 0:
            raise RuntimeError(
                f'HookStage title card failed: {r1.stderr}',
            )

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False,
            encoding='utf-8',
        ) as f:
            f.write(f"file '{card_path}'\n")
            f.write(f"file '{input_path}'\n")
            list_path = f.name

        concat_cmd = [
            'ffmpeg',
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            list_path,
            '-c',
            'copy',
            str(self.output_path),
        ]
        r2 = subprocess.run(  # noqa: S603
            concat_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if r2.returncode != 0:
            raise RuntimeError(
                f'HookStage concat failed: {r2.stderr}',
            )

        Path(card_path).unlink(missing_ok=True)
        Path(list_path).unlink(missing_ok=True)
        return self.output_path
