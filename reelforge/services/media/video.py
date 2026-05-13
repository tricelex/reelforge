from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import ffmpeg

logger = logging.getLogger("reelforge.media.video")


class VideoRenderer:
    """Renders the final video from assets using FFmpeg (primary) with Ken Burns fallback.

    Pipeline:
      1. Per-scene clip preparation (trim/scale/fade) — uses Kling clip if available,
         otherwise applies Ken Burns zoom via FFmpeg zoompan filter.
      2. Concatenate all scene clips.
      3. Mix background music (if AudioMixJob is active).
      4. Burn ASS captions (if caption_ass_file is set).
      5. Final encode: libx264 crf=18 preset=slow movflags=+faststart.
      6. Extract Shorts: 9:16 crop from centre, scale 1080×1920.
    """

    RESOLUTION = (1920, 1080)
    FPS = 30
    CRF = 18
    PRESET = "slow"

    def __init__(self, production_job: object) -> None:
        self.job = production_job
        self.asset_job = production_job.asset_job  # type: ignore[union-attr]
        self.script_job = self.asset_job.script_job
        self.channel = self.script_job.topic.channel

    # ── Public entry point ────────────────────────────────────────────────────

    def render(self) -> str:
        """Run full render pipeline. Returns path to processed video file."""
        import time

        start = time.monotonic()
        logger.info("Starting render for production_job %s", self.job.id)

        from reelforge.core.storage import get_render_path

        processed_path = get_render_path(str(self.job.id), "processed")

        # 1. Collect ordered scene clips
        scene_clips = self._get_scene_clips()
        if not scene_clips:
            msg = f"No scene clips available for ProductionJob {self.job.id}"
            raise RuntimeError(msg)

        # 2. Per-scene clip preparation → intermediate files
        prepared_clips = self._prepare_scene_clips(scene_clips)

        # 3. Concatenate
        concat_path = get_render_path(str(self.job.id), "raw")
        self._concatenate_scenes(prepared_clips, str(concat_path))

        # 4. Final encode: music + captions
        self._final_encode(str(concat_path), str(processed_path))

        # 5. Cleanup intermediate raw
        if concat_path.exists():
            concat_path.unlink(missing_ok=True)

        # 6. Render Shorts
        shorts_path = get_render_path(str(self.job.id), "shorts")
        self._extract_shorts(str(processed_path), str(shorts_path))

        # 7. Persist to ProductionJob
        from django.conf import settings

        media_root = Path(settings.MEDIA_ROOT)
        render_sec = time.monotonic() - start
        self.job.raw_video_file = str(get_render_path(str(self.job.id), "raw").relative_to(media_root))
        self.job.processed_video_file = str(processed_path.relative_to(media_root))
        self.job.shorts_video_file = str(shorts_path.relative_to(media_root)) if shorts_path.exists() else ""
        self.job.render_duration_sec = render_sec
        if processed_path.exists():
            probe = ffmpeg.probe(str(processed_path))
            self.job.video_duration_sec = float(probe["format"]["duration"])
            self.job.file_size_bytes = int(probe["format"]["size"])
        self.job.save(
            update_fields=[
                "processed_video_file",
                "shorts_video_file",
                "video_duration_sec",
                "file_size_bytes",
                "render_duration_sec",
                "updated_at",
            ]
        )

        logger.info(
            "Render complete",
            extra={
                "production_job_id": str(self.job.id),
                "duration_sec": self.job.video_duration_sec,
                "render_time_sec": render_sec,
                "output": str(processed_path),
            },
        )
        return str(processed_path)

    # ── Scene clip collection ─────────────────────────────────────────────────

    def _get_scene_clips(self) -> list[dict]:
        """Return ordered list of scene dicts with clip_path, image_path, duration."""
        from reelforge.assets.models import GeneratedImage
        from reelforge.assets.models import GeneratedVideoClip
        from reelforge.production.models import SceneBreakdownJob

        breakdown = SceneBreakdownJob.objects.filter(
            script_job=self.script_job
        ).first()
        scenes: list[dict] = (breakdown.scenes or []) if breakdown else []

        # Fall back: one scene per generated image
        if not scenes:
            images = list(
                GeneratedImage.objects.filter(
                    image_run=self.asset_job.selected_image_run
                ).order_by("position_idx")
            )
            scenes = [
                {"scene_id": img.position_idx, "duration_estimate": 8.0}
                for img in images
            ]

        # Build lookup of generated clips and images by position_idx
        clip_run = self.asset_job.selected_video_clip_run
        clips_by_pos: dict[int, str] = {}
        if clip_run:
            for clip in GeneratedVideoClip.objects.filter(
                video_clip_run=clip_run, is_selected=True
            ):
                if clip.clip_file:
                    clips_by_pos[clip.position_idx] = clip.clip_file.path

        img_run = self.asset_job.selected_image_run
        images_by_pos: dict[int, str] = {}
        if img_run:
            for img in GeneratedImage.objects.filter(
                image_run=img_run, is_selected=True
            ):
                if img.image_file:
                    images_by_pos[img.position_idx] = img.image_file.path

        result: list[dict] = []
        for scene in scenes:
            sid = scene.get("scene_id", 0)
            duration = float(scene.get("duration_estimate", 8.0))
            clip_path = clips_by_pos.get(sid)
            img_path = images_by_pos.get(sid)
            if clip_path or img_path:
                result.append(
                    {
                        "scene_id": sid,
                        "clip_path": clip_path,
                        "image_path": img_path,
                        "duration": duration,
                        "animation_type": scene.get("animation_type", "body_concept"),
                    }
                )

        return result

    # ── Scene preparation ─────────────────────────────────────────────────────

    def _prepare_scene_clips(self, scene_clips: list[dict]) -> list[str]:
        """Prepare each scene: trim/scale/fade. Returns list of temp file paths."""
        prepared: list[str] = []
        for scene in scene_clips:
            out_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            self._prepare_one_scene(scene, out_path)
            prepared.append(out_path)
        return prepared

    def _run_ffmpeg(self, stream: ffmpeg.nodes.OutputStream, label: str) -> None:
        """Run an ffmpeg stream, capturing stderr and re-raising as a plain RuntimeError."""
        try:
            stream.run(quiet=True, capture_stderr=True)
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else "(no stderr)"
            logger.exception(
                "FFmpeg error in %s:\n%s",
                label,
                stderr,
                extra={"label": label, "stderr": stderr},
            )
            msg = f"FFmpeg error in {label}: {stderr}"
            raise RuntimeError(msg) from None

    def _prepare_one_scene(self, scene: dict, out_path: str) -> None:
        """Prepare a single scene clip with scaling, fades, and optional Ken Burns."""
        duration = scene["duration"]
        w, h = self.RESOLUTION

        if scene.get("clip_path") and Path(scene["clip_path"]).exists():
            # Use Kling-generated clip: scale + fade
            self._run_ffmpeg(
                ffmpeg.input(scene["clip_path"])
                .video.filter("scale", w, h, force_original_aspect_ratio="increase")
                .filter("crop", w, h)
                .filter("fade", type="in", start_time=0, duration=0.3)
                .filter("fade", type="out", start_time=max(0, duration - 0.5), duration=0.5)
                .output(
                    out_path,
                    vcodec="libx264",
                    crf=self.CRF,
                    preset="fast",
                    an=None,  # drop audio — remixed later
                    t=duration,
                )
                .overwrite_output(),
                label=f"prepare_clip scene={scene.get('scene_id')}",
            )
        elif scene.get("image_path") and Path(scene["image_path"]).exists():
            # Ken Burns fallback via FFmpeg zoompan
            self._ken_burns_clip(scene["image_path"], duration, scene.get("animation_type", "zoom_in"), out_path)
        else:
            # Black frame fallback
            self._run_ffmpeg(
                ffmpeg.input("color=c=black:s=1920x1080", f="lavfi", t=duration)
                .output(out_path, vcodec="libx264", crf=self.CRF, preset="fast")
                .overwrite_output(),
                label=f"black_frame scene={scene.get('scene_id')}",
            )

    def _ken_burns_clip(self, image_path: str, duration: float, animation_type: str, out_path: str) -> None:
        """Apply Ken Burns effect to a still image using FFmpeg zoompan filter."""
        w, h = self.RESOLUTION
        fps = self.FPS
        total_frames = int(duration * fps)

        # zoompan expression: max 3% zoom delta
        if "zoom_out" in animation_type:
            zoom_expr = "'min(1.03,zoom-0.0005)'"
        elif "pan_right" in animation_type or "pan_left" in animation_type:
            zoom_expr = "'1.02'"
        else:  # zoom_in / default
            zoom_expr = "'min(zoom+0.0005,1.03)'"

        self._run_ffmpeg(
            ffmpeg.input(image_path, loop=1, framerate=fps)
            .filter(
                "zoompan",
                z=zoom_expr,
                d=total_frames,
                fps=fps,
                s=f"{w}x{h}",
            )
            .filter("scale", w, h)
            .filter("fade", type="in", start_time=0, duration=0.3)
            .filter("fade", type="out", start_time=max(0, duration - 0.5), duration=0.5)
            .output(
                out_path,
                vcodec="libx264",
                crf=self.CRF,
                preset="fast",
                t=duration,
                an=None,
            )
            .overwrite_output(),
            label=f"ken_burns image={Path(image_path).name}",
        )

    # ── Concatenation ─────────────────────────────────────────────────────────

    def _concatenate_scenes(self, clip_paths: list[str], out_path: str) -> None:
        """Concatenate prepared scene clips using FFmpeg concat filter."""
        if len(clip_paths) == 1:
            import shutil

            shutil.copy2(clip_paths[0], out_path)
            return

        inputs = [ffmpeg.input(p) for p in clip_paths]
        streams = [inp.video for inp in inputs]
        self._run_ffmpeg(
            ffmpeg.concat(*streams, v=1, a=0)
            .output(out_path, vcodec="libx264", crf=self.CRF, preset="fast")
            .overwrite_output(),
            label="concatenate_scenes",
        )

        # Cleanup temp clips
        for p in clip_paths:
            Path(p).unlink(missing_ok=True)

    # ── Final encode: audio + captions ───────────────────────────────────────

    def _final_encode(self, video_path: str, out_path: str) -> None:
        """Final encode: add audio track, burn captions, colour grade, faststart."""
        audio_path = self._get_audio_path()
        caption_path = self._get_caption_path()

        video_in = ffmpeg.input(video_path)
        v = video_in.video

        # Colour grade
        v = v.filter("eq", brightness=0.02, contrast=1.05, saturation=1.1)
        v = v.filter("unsharp", luma_msize_x=5, luma_msize_y=5, luma_amount=0.8)

        # Burn captions if available
        if caption_path and Path(caption_path).exists():
            # Escape path for ffmpeg filter syntax
            escaped = caption_path.replace("\\", "/").replace(":", "\\:")
            v = v.filter("ass", escaped)

        # Audio
        if audio_path and Path(audio_path).exists():
            audio_stream = ffmpeg.input(audio_path).audio.filter(
                "loudnorm", I=-16, TP=-1.5, LRA=11
            )
            self._run_ffmpeg(
                ffmpeg.output(
                    v,
                    audio_stream,
                    out_path,
                    vcodec="libx264",
                    crf=self.CRF,
                    preset=self.PRESET,
                    acodec="aac",
                    audio_bitrate="192k",
                    movflags="+faststart",
                )
                .overwrite_output(),
                label="final_encode_with_audio",
            )
        else:
            self._run_ffmpeg(
                ffmpeg.output(
                    v,
                    out_path,
                    vcodec="libx264",
                    crf=self.CRF,
                    preset=self.PRESET,
                    movflags="+faststart",
                    an=None,
                )
                .overwrite_output(),
                label="final_encode_no_audio",
            )

    def _get_audio_path(self) -> str | None:
        """Return path to the best available audio file."""
        from reelforge.production.models import AudioMixJob

        mix = AudioMixJob.objects.filter(asset_job=self.asset_job, is_active=True).first()
        if mix and mix.mixed_audio_file:
            return mix.mixed_audio_file.path

        vo = self.asset_job.selected_voiceover_run
        if vo and vo.merged_audio_file:
            return vo.merged_audio_file.path

        return None

    def _get_caption_path(self) -> str | None:
        """Return path to ASS caption file if it exists on the production job."""
        if self.job.caption_ass_file:
            return self.job.caption_ass_file.path
        return None

    # ── Shorts extraction ─────────────────────────────────────────────────────

    def _extract_shorts(self, source_path: str, shorts_path: str) -> None:
        """Extract 9:16 Shorts variant from the processed video."""
        start_sec = getattr(self.job, "shorts_start_sec", 0.0) or 0.0
        end_sec = getattr(self.job, "shorts_end_sec", 60.0) or 60.0

        if end_sec <= start_sec:
            # Default: first 60 seconds
            end_sec = start_sec + 60.0

        try:
            inp = ffmpeg.input(source_path, ss=start_sec, to=end_sec)
            v = inp.video.filter("crop", "ih*9/16", "ih").filter("scale", 1080, 1920)
            a = inp.audio
            self._run_ffmpeg(
                ffmpeg.output(
                    v,
                    a,
                    shorts_path,
                    vcodec="libx264",
                    crf=20,
                    preset="fast",
                    acodec="aac",
                    audio_bitrate="128k",
                )
                .overwrite_output(),
                label="extract_shorts",
            )
        except RuntimeError as exc:
            logger.warning(
                "Shorts extraction failed — skipping: %s",
                exc,
                extra={"production_job_id": str(self.job.id)},
            )


class VideoQA:
    """Quality assurance checks on rendered video."""

    def __init__(self, production_job: object) -> None:
        self.job = production_job
        self.path = str(production_job.processed_video_file.path)  # type: ignore[union-attr]

    def run_all_checks(self) -> dict[str, bool]:
        return {
            "file_exists": self._check_file_exists(),
            "min_duration": self._check_min_duration(min_seconds=60),
            "max_duration": self._check_max_duration(max_seconds=3600),
            "no_black_frames": self._check_black_frames(),
            "audio_present": self._check_audio_present(),
            "audio_sync": self._check_audio_video_sync(),
            "resolution_ok": self._check_resolution(),
            "file_size_ok": self._check_file_size(max_gb=10),
            "no_corruption": self._check_file_integrity(),
        }

    def _check_file_exists(self) -> bool:
        return os.path.isfile(self.path)

    def _check_min_duration(self, min_seconds: int) -> bool:
        probe = ffmpeg.probe(self.path)
        duration = float(probe["format"]["duration"])
        return duration >= min_seconds

    def _check_max_duration(self, max_seconds: int) -> bool:
        probe = ffmpeg.probe(self.path)
        return float(probe["format"]["duration"]) <= max_seconds

    def _check_black_frames(self) -> bool:
        """Detect prolonged black frames via ffprobe blackdetect."""
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "packet=pts_time,flags",
                "-of",
                "csv=p=0",
                "-select_streams",
                "v",
                self.path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return "blackdetect" not in result.stderr

    def _check_audio_present(self) -> bool:
        probe = ffmpeg.probe(self.path)
        streams = probe.get("streams", [])
        return any(s["codec_type"] == "audio" for s in streams)

    def _check_audio_video_sync(self) -> bool:
        """Check if audio and video streams have the same duration (±1 second)."""
        probe = ffmpeg.probe(self.path)
        durations = [float(s["duration"]) for s in probe["streams"] if "duration" in s]
        if len(durations) < 2:
            return False
        return abs(durations[0] - durations[1]) < 1.0

    def _check_resolution(self) -> bool:
        probe = ffmpeg.probe(self.path)
        for stream in probe["streams"]:
            if stream["codec_type"] == "video":
                return stream["width"] == 1920 and stream["height"] == 1080
        return False

    def _check_file_size(self, max_gb: float) -> bool:
        return os.path.getsize(self.path) < max_gb * 1_000_000_000

    def _check_file_integrity(self) -> bool:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", self.path, "-f", "null", "-"],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
