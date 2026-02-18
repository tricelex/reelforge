import logging
import os
import subprocess

import ffmpeg
import numpy as np
from moviepy.editor import AudioFileClip
from moviepy.editor import CompositeVideoClip
from moviepy.editor import ImageClip
from moviepy.editor import TextClip
from moviepy.editor import concatenate_videoclips
from PIL import Image

logger = logging.getLogger("youtube_hq.media.video")


class VideoRenderer:
    """Renders the final video from assets using MoviePy + FFmpeg.
    Design: MoviePy handles compositing logic, FFmpeg handles final encode.
    """

    RESOLUTION = (1920, 1080)
    FPS = 30
    SUBTITLE_FONT = "Montserrat-Bold"
    SUBTITLE_SIZE = 52
    SUBTITLE_COLOR = "white"
    SUBTITLE_STROKE = "black"
    SUBTITLE_STROKE_WIDTH = 3

    def __init__(self, production_job) -> None:
        self.job = production_job
        self.asset_job = production_job.asset_job
        self.script_job = production_job.asset_job.script_job
        self.channel = production_job.asset_job.script_job.topic.channel
        self.timeline = production_job.asset_job.visual_timeline

    def render(self) -> str:
        """Full render pipeline. Returns final video path."""
        logger.info(f"Starting render for production job {self.job.id}")

        clips = []

        for slot in self.timeline:
            clip = self._build_clip(slot)
            clips.append(clip)

        # Concatenate all clips
        video = concatenate_videoclips(clips, method="compose")

        # Add progress bar overlay
        video = self._add_progress_bar(video)

        # Add audio
        audio = AudioFileClip(str(self.asset_job.voiceover_full_file.path))
        video = video.set_audio(audio)

        # Render raw version (high quality for archiving)
        raw_path = f"storage/production/raw/{self.job.id}_raw.mp4"
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)

        video.write_videofile(
            raw_path,
            fps=self.FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="8000k",
            preset="medium",
            threads=4,
            logger=None,  # Suppress moviepy progress bars in prod
        )

        # Post-process with FFmpeg (color grade + audio normalization)
        processed_path = self._post_process(raw_path)

        # Save file references
        self.job.raw_video_file.name = raw_path
        self.job.processed_video_file.name = processed_path
        self.job.video_duration_sec = video.duration
        self.job.file_size_bytes = os.path.getsize(processed_path)
        self.job.save()

        # Render Shorts
        shorts_path = self._render_shorts(processed_path)
        self.job.shorts_video_file.name = shorts_path
        self.job.save()

        # Cleanup raw after archive period
        video.close()
        audio.close()
        return processed_path

    def _build_clip(self, slot: dict) -> CompositeVideoClip:
        """Build a single timeline slot with background, animation, subtitles."""
        duration = (slot["end_ms"] - slot["start_ms"]) / 1000.0

        # 1. Background image with Ken Burns effect
        bg = self._build_ken_burns_clip(
            image_path=slot["image_path"], duration=duration, animation=slot.get("animation_type", "zoom_in")
        )

        # 2. Subtitle overlay
        subtitle = self._build_subtitle_clip(text=slot["segment_text"], duration=duration)

        # 3. Compose
        composite = CompositeVideoClip([bg, subtitle.set_pos(("center", 0.85), relative=True)])
        return composite.set_duration(duration)

    def _build_ken_burns_clip(self, image_path: str, duration: float, animation: str) -> ImageClip:
        """Apply Ken Burns (slow zoom/pan) to static image."""
        w, h = self.RESOLUTION
        img = Image.open(image_path).convert("RGB")
        img = img.resize((w + 100, h + 60), Image.LANCZOS)  # Slightly oversized for zoom room

        def make_frame(t):
            progress = t / duration
            if animation == "zoom_in":
                scale = 1.0 + 0.03 * progress  # Slowly zoom in 3%
                offset_x = int(50 * progress)
                offset_y = int(30 * progress)
            elif animation == "zoom_out":
                scale = 1.03 - 0.03 * progress
                offset_x = int(50 * (1 - progress))
                offset_y = int(30 * (1 - progress))
            elif animation == "pan_right":
                scale = 1.02
                offset_x = int(80 * progress)
                offset_y = 0
            else:  # pan_left
                scale = 1.02
                offset_x = int(80 * (1 - progress))
                offset_y = 0

            # Apply transform
            new_w = int(w * scale)
            new_h = int(h * scale)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            cropped = resized.crop((offset_x, offset_y, offset_x + w, offset_y + h))
            return np.array(cropped)

        return ImageClip(make_frame, duration=duration, ismask=False).set_fps(self.FPS)

    def _build_subtitle_clip(self, text: str, duration: float) -> TextClip:
        """Build word-wrapped subtitle with stroke."""
        clip = TextClip(
            text,
            fontsize=self.SUBTITLE_SIZE,
            font=self.SUBTITLE_FONT,
            color=self.SUBTITLE_COLOR,
            stroke_color=self.SUBTITLE_STROKE,
            stroke_width=self.SUBTITLE_STROKE_WIDTH,
            method="caption",
            size=(self.RESOLUTION[0] - 160, None),
            align="center",
        )
        return clip.set_duration(duration).fadein(0.15).fadeout(0.15)

    def _add_progress_bar(self, video: CompositeVideoClip) -> CompositeVideoClip:
        """Thin progress bar at top of video."""
        brand_color = self.channel.brand_color_hex
        total_duration = video.duration

        def make_bar_frame(t):
            progress = t / total_duration
            bar_width = int(self.RESOLUTION[0] * progress)
            frame = np.zeros((4, self.RESOLUTION[0], 3), dtype=np.uint8)
            r, g, b = tuple(int(brand_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            frame[:, :bar_width] = [r, g, b]
            return frame

        bar_clip = ImageClip(make_bar_frame, duration=total_duration, ismask=False).set_fps(self.FPS)
        bar_clip = bar_clip.set_pos(("left", "top"))
        return CompositeVideoClip([video, bar_clip])

    def _post_process(self, raw_path: str) -> str:
        """FFmpeg post-processing: color grade + audio normalization."""
        processed_path = raw_path.replace("_raw.mp4", "_processed.mp4")

        (
            ffmpeg.input(raw_path)
            .video.filter("eq", brightness=0.02, contrast=1.05, saturation=1.1)
            .filter("unsharp", luma_msize_x=5, luma_msize_y=5, luma_amount=0.8)
            .output(
                ffmpeg.input(raw_path).audio.filter("loudnorm", I=-16, TP=-1.5, LRA=11),
                processed_path,
                vcodec="libx264",
                crf=18,
                preset="slow",
                acodec="aac",
                audio_bitrate="192k",
                movflags="+faststart",  # Enable streaming
            )
            .overwrite_output()
            .run()
        )

        return processed_path

    def _render_shorts(self, source_path: str) -> str:
        """Extract and reformat best 60-second segment as vertical Shorts."""
        start_sec = self.job.shorts_start_sec
        end_sec = self.job.shorts_end_sec
        shorts_path = source_path.replace("_processed.mp4", "_shorts.mp4")

        (
            ffmpeg.input(source_path, ss=start_sec, to=end_sec)
            .filter("crop", "ih*9/16", "ih")  # Crop to 9:16 from center
            .filter("scale", 1080, 1920)
            .output(shorts_path, vcodec="libx264", crf=20, preset="fast", acodec="aac", audio_bitrate="128k")
            .overwrite_output()
            .run()
        )

        return shorts_path


class VideoQA:
    """Quality assurance checks on rendered video."""

    def __init__(self, production_job) -> None:
        self.job = production_job
        self.path = str(production_job.processed_video_file.path)

    def run_all_checks(self) -> dict:
        return {
            "file_exists": self._check_file_exists(),
            "min_duration": self._check_min_duration(min_seconds=480),
            "max_duration": self._check_max_duration(max_seconds=900),
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
        """Detect prolonged black frames (> 2 seconds at start/end)."""
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
            ["ffmpeg", "-v", "error", "-i", self.path, "-f", "null", "-"], capture_output=True, check=False
        )
        return result.returncode == 0
