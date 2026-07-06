"""TimedOverlayStage — stage 7: text or image overlays with time ranges."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args

if TYPE_CHECKING:
    from server.apps.clips.models import ClipTimedOverlay

logger = logging.getLogger('reelforge.rendering.clip_stages')

_ANIM_FADE_DURATION = 0.3


def _animation_alpha_expr(
    animation: str,
    *,
    start: float,
    end: float,
    opacity: float = 1.0,
) -> str:
    """Return a drawtext `alpha=` expression for the fade in/out window."""
    opacity_str = str(int(opacity)) if opacity == int(opacity) else str(opacity)
    if animation in {
        'NONE',
        'SLIDE_LEFT',
        'SLIDE_RIGHT',
        'SLIDE_UP',
        'SLIDE_DOWN',
    }:
        return opacity_str
    d = _ANIM_FADE_DURATION
    return (
        f'if(lt(t,{start + d}),(t-{start})/{d}*{opacity},'
        f'if(lt(t,{end - d}),{opacity},({end}-t)/{d}*{opacity}))'
    )


def _animation_xy_expr(
    animation: str,
    *,
    base_x: int,
    base_y: int,
    start: float,
    end: float,
) -> tuple[str, str]:
    """Return (x_expr, y_expr) — slides the element in/out along one axis."""
    d = _ANIM_FADE_DURATION
    offset = 60
    if animation == 'SLIDE_LEFT':
        x = (
            f'if(lt(t,{start + d}),{base_x}-{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_x},'
            f'{base_x}-{offset}*(1-({end}-t)/{d})))'
        )
        return x, str(base_y)
    if animation == 'SLIDE_RIGHT':
        x = (
            f'if(lt(t,{start + d}),{base_x}+{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_x},'
            f'{base_x}+{offset}*(1-({end}-t)/{d})))'
        )
        return x, str(base_y)
    if animation == 'SLIDE_UP':
        y = (
            f'if(lt(t,{start + d}),{base_y}-{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_y},'
            f'{base_y}-{offset}*(1-({end}-t)/{d})))'
        )
        return str(base_x), y
    if animation == 'SLIDE_DOWN':
        y = (
            f'if(lt(t,{start + d}),{base_y}+{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_y},'
            f'{base_y}+{offset}*(1-({end}-t)/{d})))'
        )
        return str(base_x), y
    return str(base_x), str(base_y)


def _shape_mask_filter(shape: str, width: int) -> str:
    """Return a geq alpha-mask filter for CIRCLE/ROUNDED, or '' for RECTANGLE."""
    if shape == 'CIRCLE':
        r = width // 2
        return (
            f',format=rgba,geq='
            f"r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lte(pow(X-{r}\\,2)+pow(Y-{r}\\,2)\\,pow({r}\\,2))\\,255\\,0)'"
        )
    if shape == 'ROUNDED':
        return ',format=rgba'
    return ''


@final
@dataclass
class TimedOverlayStage(RenderStage):
    """Stage 7: Apply timed text/image overlays."""

    output_path: Path
    timed_overlays: list[ClipTimedOverlay] = field(default_factory=list)
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'timed_overlays'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 8

    @override
    def should_run(self) -> bool:
        """Return True if there are overlays to apply."""
        return len(self.timed_overlays) > 0

    @override
    def run(self, input_path: Path) -> Path:
        """Apply all timed overlays."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        current = str(input_path)
        any_applied = False
        for overlay in self.timed_overlays:
            if overlay.overlay_type == 'TEXT' and overlay.text:
                current = self._apply_text(current, overlay)
                any_applied = True
            elif overlay.overlay_type == 'IMAGE' and overlay.image_asset:
                current = self._apply_media_overlay(
                    current,
                    overlay,
                    overlay.image_asset.file.read(),
                    is_video=False,
                )
                any_applied = True
            elif overlay.overlay_type == 'VIDEO' and overlay.video_asset:
                current = self._apply_media_overlay(
                    current,
                    overlay,
                    overlay.video_asset.file.read(),
                    is_video=True,
                )
                any_applied = True
        if not any_applied:
            return input_path
        final_path = Path(current)
        if final_path != self.output_path:
            final_path.rename(self.output_path)
        return self.output_path

    def _apply_text(self, input_path: str, overlay: ClipTimedOverlay) -> str:
        from server.apps.rendering.clip_stages.fonts import (  # noqa: PLC0415
            resolve_drawtext_font,
        )

        safe = overlay.text.replace("'", "\\'").replace(':', '\\:')
        font_path, _family = resolve_drawtext_font(
            overlay.font,
            overlay.font_asset,
        )
        safe_font = font_path.replace("'", "\\'").replace(':', '\\:')
        alpha_expr = _animation_alpha_expr(
            overlay.animation,
            start=overlay.start_sec,
            end=overlay.end_sec,
            opacity=overlay.opacity,
        )
        x_expr, y_expr = _animation_xy_expr(
            overlay.animation,
            base_x=overlay.x,
            base_y=overlay.y,
            start=overlay.start_sec,
            end=overlay.end_sec,
        )
        part = (
            f"drawtext=text='{safe}'"
            f':fontfile={safe_font}'
            f':fontsize={overlay.font_size}'
            f':fontcolor={overlay.color}'
            f":alpha='{alpha_expr}'"
            f":x='{x_expr}':y='{y_expr}'"
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'"
        )
        out = self._next_tmp_path()
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            input_path,
            '-vf',
            part,
            *clip_filter_encode_args(
                crf=self.crf,
                preset=self.preset,
                fps=self.fps,
                audio_bitrate=self.audio_bitrate,
            ),
            out,
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'TimedOverlayStage text ffmpeg failed: {result.stderr}',
            )
        return out

    def _apply_media_overlay(
        self,
        input_path: str,
        overlay: ClipTimedOverlay,
        media_bytes: bytes,
        *,
        is_video: bool,
    ) -> str:
        suffix = '.mp4' if is_video else '.png'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            media_path = tmp.name
        Path(media_path).write_bytes(media_bytes)

        width = overlay.width or 300
        overlay_input = (
            ['-i', media_path] if is_video else ['-loop', '1', '-i', media_path]
        )
        fade_filters = ''
        if overlay.animation != 'NONE':
            d = _ANIM_FADE_DURATION
            fade_filters = (
                f',fade=t=in:st={overlay.start_sec}:d={d}:alpha=1'
                f',fade=t=out:st={overlay.end_sec - d}:d={d}:alpha=1'
            )
        mask_filter = _shape_mask_filter(overlay.shape, width) if is_video else ''
        filter_complex = (
            f'[1:v]scale={width}:-1{mask_filter},format=rgba,'
            f'colorchannelmixer=aa={overlay.opacity}{fade_filters}[ov];'
            f"[0:v][ov]overlay={overlay.x}:{overlay.y}"
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'[vout]"
        )
        out = self._next_tmp_path()
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            input_path,
            *overlay_input,
            '-filter_complex',
            filter_complex,
            '-map',
            '[vout]',
            '-map',
            '0:a?',
            *clip_filter_encode_args(
                crf=self.crf,
                preset=self.preset,
                fps=self.fps,
                audio_bitrate=self.audio_bitrate,
            ),
            '-shortest',
            out,
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        Path(media_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f'TimedOverlayStage media ffmpeg failed: {result.stderr}',
            )
        return out

    def _next_tmp_path(self) -> str:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            return tmp.name
