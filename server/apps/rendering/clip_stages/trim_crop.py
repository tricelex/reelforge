"""TrimAndCropStage — trim + crop/compose source video to target format."""

import logging
import subprocess  # noqa: S404
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, final, override

from server.apps.clips.logic.constants import (
    BackgroundMode,
    ForegroundTreatment,
    RenderMode,
)
from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.composition import (
    MiddleZone,
    ResolvedComposition,
    blurred_background_filter,
    compose_overlay_filter,
    contain_foreground_filter,
    fill_crop_filter,
    middle_zone,
    needs_composed_background,
    resolve_layout_composition,
    solid_background_filter,
    square_crop_foreground_filter,
)
from server.apps.rendering.speaker_detection import SpeakerDetectionService

if TYPE_CHECKING:
    from server.apps.clips.models import ClipLayoutConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class TrimAndCropStage(RenderStage):
    """Stage 1: Trim source to clip boundary + crop/compose to target format."""

    source_path: Path
    start_sec: float
    end_sec: float
    output_path: Path
    layout_config: 'ClipLayoutConfig | None'
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'
    playback_speed: float = 1.0
    last_speaker_crop_result: Any = field(default=None, init=False)
    _speaker_svc: SpeakerDetectionService = field(
        default_factory=SpeakerDetectionService,
        init=False,
        repr=False,
    )

    @property
    @override
    def name(self) -> str:
        return 'trim_and_crop'

    @property
    @override
    def order(self) -> int:
        return 1

    @override
    def run(self, input_path: Path) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._build_command(input_path)
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'TrimAndCropStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path

    def _speed_filters(self) -> tuple[str, str]:
        """Return video/audio speed filters, or empty strings at 1x."""
        if abs(self.playback_speed - 1.0) < 1e-9:
            return '', ''
        video = f',setpts={1 / self.playback_speed:.6f}*PTS'
        remaining = self.playback_speed
        atempo_parts = []
        while remaining > 2.0:
            atempo_parts.append('atempo=2.0')
            remaining /= 2.0
        while remaining < 0.5:
            atempo_parts.append('atempo=0.5')
            remaining /= 0.5
        atempo_parts.append(f'atempo={remaining:.4f}')
        return video, ','.join(atempo_parts)

    def _encode_tail(self, audio_af: str) -> list[str]:
        cmd: list[str] = []
        if audio_af:
            cmd += ['-af', audio_af]
        cmd += [
            '-c:v',
            'libx264',
            '-crf',
            str(self.crf),
            '-preset',
            self.preset,
            '-c:a',
            'aac',
            '-b:a',
            self.audio_bitrate,
            '-movflags',
            'faststart',
            str(self.output_path),
        ]
        return cmd

    def _clip_duration(self) -> float:
        duration = self.end_sec - self.start_sec
        if duration <= 0:
            msg = (
                f'Invalid clip window: start={self.start_sec} '
                f'end={self.end_sec}'
            )
            raise ValueError(msg)
        return duration / self.playback_speed

    def _build_command(self, input_path: Path) -> list[str]:
        mode = (
            self.layout_config.render_mode
            if self.layout_config
            else RenderMode.CENTER_CROP
        )
        if mode == RenderMode.SPATIAL_STACK:
            return self._spatial_stack_cmd(input_path)
        if mode == RenderMode.SMART_CROP:
            return self._smart_crop_cmd(input_path)
        return self._center_crop_cmd(input_path)

    def _background_filters(
        self,
        resolved: ResolvedComposition,
        *,
        duration: float,
    ) -> tuple[str, str, str]:
        """Return (filter_prefix, background_filter, foreground_input_label)."""
        if resolved.background_mode == BackgroundMode.BLURRED_SOURCE:
            prefix = (
                f'[0:v]trim=start={self.start_sec}:end={self.end_sec},'
                f'setpts=PTS-STARTPTS,split=2[srcbg][srcfg];'
            )
            bg = blurred_background_filter(
                width=self.width,
                height=self.height,
                blur_strength=resolved.blur_strength,
                input_label='srcbg',
            )
            return prefix, bg, 'srcfg'
        bg = solid_background_filter(
            width=self.width,
            height=self.height,
            color=resolved.background_color,
            duration_sec=duration,
        )
        return '', bg, '0:v'

    def _foreground_filter(
        self,
        resolved: ResolvedComposition,
        *,
        zone: MiddleZone,
        fg_label: str,
        square_crop: tuple[int, int, int, int] | None,
    ) -> str:
        if resolved.foreground_treatment == ForegroundTreatment.SQUARE_CROP:
            lc = self.layout_config
            if square_crop is not None:
                crop_x, crop_y, crop_w, crop_h = square_crop
            else:
                crop_x = lc.manual_crop_x if lc else None
                crop_y = lc.manual_crop_y if lc else None
                crop_w = lc.manual_crop_w if lc else None
                crop_h = lc.manual_crop_h if lc else None
            return square_crop_foreground_filter(
                zone=zone,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_w=crop_w,
                crop_h=crop_h,
                input_label=fg_label,
            )
        return contain_foreground_filter(zone=zone, input_label=fg_label)

    def _composed_cmd(
        self,
        input_path: Path,
        *,
        composition: ResolvedComposition | None = None,
        square_crop: tuple[int, int, int, int] | None = None,
    ) -> list[str]:
        resolved = composition or resolve_layout_composition(self.layout_config)
        if not needs_composed_background(resolved):
            return self._fill_cmd(input_path)

        zone = middle_zone(self.width, self.height)
        video_suffix, audio_af = self._speed_filters()
        duration = self._clip_duration()
        use_blur = resolved.background_mode == BackgroundMode.BLURRED_SOURCE
        filter_prefix, bg, fg_label = self._background_filters(
            resolved,
            duration=duration,
        )
        fg_body = self._foreground_filter(
            resolved,
            zone=zone,
            fg_label=fg_label,
            square_crop=square_crop,
        )

        if not use_blur:
            if not fg_body.startswith(f'[{fg_label}]'):
                msg = f'Unexpected foreground filter: {fg_body}'
                raise ValueError(msg)
            fg_body = (
                f'[{fg_label}]trim=start={self.start_sec}:end={self.end_sec},'
                f'setpts=PTS-STARTPTS,' + fg_body.removeprefix(f'[{fg_label}]')
            )

        overlay = compose_overlay_filter(
            zone=zone,
            video_suffix=video_suffix,
            fps=self.fps,
        )
        filter_complex = f'{filter_prefix}{bg};{fg_body};{overlay}'
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-filter_complex',
            filter_complex,
            '-map',
            '[vout]',
            '-map',
            '0:a?',
            '-shortest',
        ]
        cmd += self._encode_tail(audio_af)
        return cmd

    def _fill_cmd(self, input_path: Path) -> list[str]:
        video_suffix, audio_af = self._speed_filters()
        vf = (
            f'{fill_crop_filter(width=self.width, height=self.height)},'
            f'fps={self.fps}{video_suffix}'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-ss',
            str(self.start_sec),
            '-to',
            str(self.end_sec),
            '-vf',
            vf,
        ]
        cmd += self._encode_tail(audio_af)
        return cmd

    def _center_crop_cmd(self, input_path: Path) -> list[str]:
        composition = resolve_layout_composition(self.layout_config)
        if needs_composed_background(composition):
            return self._composed_cmd(input_path, composition=composition)
        return self._fill_cmd(input_path)

    def _smart_crop_cmd(self, input_path: Path) -> list[str]:
        from server.apps.rendering.clip_stages.probe import (  # noqa: PLC0415
            sync_ffprobe_dimensions,
        )
        from server.apps.rendering.speaker_detection import (  # noqa: PLC0415
            clamp_crop_rect,
        )

        composition = resolve_layout_composition(self.layout_config)
        if composition.foreground_treatment == ForegroundTreatment.CONTAIN:
            return self._composed_cmd(input_path, composition=composition)

        lc = self.layout_config
        result = self._speaker_svc.detect(
            video_path=input_path,
            start_sec=self.start_sec,
            end_sec=self.end_sec,
            manual_crop_x=lc.manual_crop_x if lc else None,
            manual_crop_y=lc.manual_crop_y if lc else None,
            manual_crop_w=lc.manual_crop_w if lc else None,
            manual_crop_h=lc.manual_crop_h if lc else None,
            target_width=self.width,
            target_height=self.height,
        )
        self.last_speaker_crop_result = result
        frame_w, frame_h = sync_ffprobe_dimensions(str(input_path))
        if frame_w is None or frame_h is None:
            logger.warning(
                'SMART_CROP could not probe source dimensions - '
                'falling back to center crop',
            )
            return self._center_crop_cmd(input_path)
        clamped = clamp_crop_rect(
            result.crop_x,
            result.crop_y,
            result.crop_w,
            result.crop_h,
            frame_w,
            frame_h,
        )
        if clamped is None:
            return self._center_crop_cmd(input_path)
        crop_x, crop_y, crop_w, crop_h = clamped
        if (crop_w, crop_h) != (result.crop_w, result.crop_h) or (
            crop_x,
            crop_y,
        ) != (result.crop_x, result.crop_y):
            logger.warning(
                'SMART_CROP clamped oversized crop '
                '%sx%s@%s,%s -> %sx%s@%s,%s for source %sx%s',
                result.crop_w,
                result.crop_h,
                result.crop_x,
                result.crop_y,
                crop_w,
                crop_h,
                crop_x,
                crop_y,
                frame_w,
                frame_h,
            )

        if composition.foreground_treatment == ForegroundTreatment.SQUARE_CROP:
            side = min(crop_w, crop_h)
            cx = crop_x + (crop_w - side) // 2
            cy = crop_y + (crop_h - side) // 2
            return self._composed_cmd(
                input_path,
                composition=composition,
                square_crop=(cx, cy, side, side),
            )

        video_suffix, audio_af = self._speed_filters()
        vf = (
            f'crop={crop_w}:{crop_h}:{crop_x}:{crop_y},'
            f'scale={self.width}:{self.height},fps={self.fps}{video_suffix}'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-ss',
            str(self.start_sec),
            '-to',
            str(self.end_sec),
            '-vf',
            vf,
        ]
        cmd += self._encode_tail(audio_af)
        return cmd

    def _spatial_stack_cmd(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        if lc is None or not lc.has_spatial_regions:
            logger.warning(
                'SPATIAL_STACK has no regions - falling back to center crop',
            )
            return self._center_crop_cmd(input_path)
        out_w, out_h = self.width, self.height
        a_out_h = int(out_h * lc.stack_ratio)
        b_out_h = out_h - a_out_h
        video_suffix, audio_af = self._speed_filters()
        filter_complex = (
            f'[0:v]trim=start={self.start_sec}:end={self.end_sec},'
            f'setpts=PTS-STARTPTS,'
            f'crop={lc.region_a_w}:{lc.region_a_h}'
            f':{lc.region_a_x}:{lc.region_a_y},'
            f'scale={out_w}:{a_out_h}[top];'
            f'[0:v]trim=start={self.start_sec}:end={self.end_sec},'
            f'setpts=PTS-STARTPTS,'
            f'crop={lc.region_b_w}:{lc.region_b_h}'
            f':{lc.region_b_x}:{lc.region_b_y},'
            f'scale={out_w}:{b_out_h}[bottom];'
            f'[top][bottom]vstack=inputs=2{video_suffix}[out]'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-filter_complex',
            filter_complex,
            '-map',
            '[out]',
            '-map',
            '0:a',
        ]
        cmd += self._encode_tail(audio_af)
        return cmd
