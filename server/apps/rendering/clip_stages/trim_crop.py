"""TrimAndCropStage — trim + crop source video to target format."""

import logging
import subprocess  # noqa: S404
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, final, override

from server.apps.clips.logic.constants import RenderMode
from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.speaker_detection import SpeakerDetectionService

if TYPE_CHECKING:
    from server.apps.clips.models import ClipLayoutConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class TrimAndCropStage(RenderStage):
    """Stage 1: Trim source to clip boundary + crop to target aspect ratio."""

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
        """Return (video_vf_suffix, audio_af) for playback_speed, or ('', '')."""
        if self.playback_speed == 1.0:
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

    def _center_crop_cmd(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        fit_mode = lc.fit_mode if lc else 'CROP'
        video_suffix, audio_af = self._speed_filters()
        if fit_mode == 'BLUR_FILL':
            vf = (
                f'split=2[bg][fg];'
                f'[bg]scale={self.width}:{self.height}:'
                f'force_original_aspect_ratio=increase,'
                f'crop={self.width}:{self.height},boxblur=20:5[bgblur];'
                f'[fg]scale={self.width}:{self.height}:'
                f'force_original_aspect_ratio=decrease[fgfit];'
                f'[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2,'
                f'fps={self.fps}{video_suffix}'
            )
        else:
            # Centered crop to the target aspect ratio: no-op when the
            # source already matches (e.g. 16:9 source -> 16:9 target).
            vf = (
                f"crop='min(iw,ih*{self.width}/{self.height})'"
                f":'min(ih,iw*{self.height}/{self.width})',"
                f'scale={self.width}:{self.height},'
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

    def _smart_crop_cmd(self, input_path: Path) -> list[str]:
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
        video_suffix, audio_af = self._speed_filters()
        vf = (
            f'crop={result.crop_w}:{result.crop_h}'
            f':{result.crop_x}:{result.crop_y},'
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
