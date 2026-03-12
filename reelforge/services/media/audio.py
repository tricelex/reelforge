import json
import logging
import os
import re
import subprocess

import numpy as np
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range
from pydub.effects import normalize

logger = logging.getLogger("reelforge.media.audio")


class AudioProcessor:
    """Full audio pipeline for voiceover production."""

    YOUTUBE_TARGET_LUFS = -16.0
    YOUTUBE_TRUE_PEAK = -1.5

    def merge_voiceover_segments(
        self,
        segment_files: list[dict],  # [{path, segment_id, pause_after_ms}]
        output_path: str,
    ) -> dict:
        """Concatenate audio segments with natural pauses between them."""
        combined = AudioSegment.empty()

        for i, seg in enumerate(sorted(segment_files, key=lambda x: x["segment_id"])):
            audio = AudioSegment.from_file(seg["path"])
            # Normalize individual segment volume
            audio = normalize(audio, headroom=1.0)
            combined += audio

            # Add pause if not last segment
            if i < len(segment_files) - 1:
                pause_ms = seg.get("pause_after_ms", 200)
                combined += AudioSegment.silent(duration=pause_ms)

        # Master processing
        combined = self._master_audio(combined)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        combined.export(
            output_path, format="mp3", bitrate="192k", parameters=["-ar", "44100"]
        )  # YouTube standard sample rate

        return {"path": output_path, "duration_sec": len(combined) / 1000.0, "size_bytes": os.path.getsize(output_path)}

    def _master_audio(self, audio: AudioSegment) -> AudioSegment:
        """Apply mastering chain: compression → EQ → loudness normalize."""
        # Light dynamic compression
        audio = compress_dynamic_range(audio, threshold=-20.0, ratio=3.0, attack=5.0, release=50.0)
        # Loudness normalization to YouTube standard (-16 LUFS)
        return self._loudness_normalize(audio)

    def _loudness_normalize(self, audio: AudioSegment) -> AudioSegment:
        """Normalize to -16 LUFS using two-pass integrated loudness measurement.

        Pass 1 measures the actual loudness; pass 2 applies linear normalization
        using the measured values for accurate, artefact-free results.
        """
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in,
            tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out,
        ):
            audio.export(tmp_in.name, format="wav")

            # Pass 1: measure integrated loudness
            proc1 = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", tmp_in.name,
                    "-af",
                    f"loudnorm=I={self.YOUTUBE_TARGET_LUFS}:TP={self.YOUTUBE_TRUE_PEAK}:LRA=11:print_format=json",
                    "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
            )
            # loudnorm print_format=json writes the stats block to stderr
            match = re.search(r"\{[^{}]+\}", proc1.stderr, re.DOTALL)
            if match:
                stats: dict[str, str] = json.loads(match.group())
            else:
                logger.warning("loudnorm pass 1: could not parse stats JSON — falling back to defaults")
                stats = {}

            # Pass 2: apply linear normalization with measured values
            af_pass2 = (
                f"loudnorm=I={self.YOUTUBE_TARGET_LUFS}:TP={self.YOUTUBE_TRUE_PEAK}:LRA=11"
                f":measured_I={stats.get('input_i', self.YOUTUBE_TARGET_LUFS)}"
                f":measured_TP={stats.get('input_tp', self.YOUTUBE_TRUE_PEAK)}"
                f":measured_LRA={stats.get('input_lra', 11)}"
                f":measured_thresh={stats.get('input_thresh', -26)}"
                f":linear=true:print_format=none"
            )
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_in.name, "-af", af_pass2, "-ar", "44100", tmp_out.name],
                check=True,
                capture_output=True,
            )

            normalized = AudioSegment.from_wav(tmp_out.name)
            os.unlink(tmp_in.name)
            os.unlink(tmp_out.name)

        return normalized

    def normalize_only(self, input_path: str, output_path: str) -> dict:
        """Normalize a voiceover file to YouTube loudness standard with no music mixing."""
        import subprocess

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-af", f"loudnorm=I={self.YOUTUBE_TARGET_LUFS}:TP={self.YOUTUBE_TRUE_PEAK}:LRA=11",
                "-ar", "44100", "-b:a", "192k",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return {
            "path": output_path,
            "duration_sec": len(AudioSegment.from_file(output_path)) / 1000.0,
        }

    def mix_with_background_music(
        self,
        voiceover_path: str,
        music_path: str,
        output_path: str,
        music_volume_pct: float = 0.08,
        fade_in_sec: float = 2.0,
        fade_out_sec: float = 3.0,
    ) -> dict:
        """Mix voiceover with background music at specified level."""
        voice = AudioSegment.from_file(voiceover_path)
        music = AudioSegment.from_file(music_path)
        total_ms = len(voice)

        # Loop music if shorter than voiceover
        if len(music) < total_ms:
            loops = (total_ms // len(music)) + 2
            music = music * loops
        music = music[:total_ms]

        # Apply fade in/out
        music = music.fade_in(int(fade_in_sec * 1000)).fade_out(int(fade_out_sec * 1000))

        # Convert percentage to dB reduction
        # music_volume_pct=0.08 → voice is ~22dB louder than music
        voice_db = voice.dBFS
        music_target_db = voice_db + 20 * np.log10(music_volume_pct)
        db_adjustment = music_target_db - music.dBFS
        music = music + db_adjustment

        # Mix
        mixed = voice.overlay(music)
        mixed = self._loudness_normalize(mixed)
        mixed.export(output_path, format="mp3", bitrate="320k")

        return {"path": output_path, "duration_sec": len(mixed) / 1000.0}

    def get_segment_timings(self, segment_files: list[dict]) -> list[dict]:
        """Calculate start/end timestamps for each segment in the merged audio."""
        timings = []
        current_ms = 0
        silence_ms = 200

        for seg in sorted(segment_files, key=lambda x: x["segment_id"]):
            audio = AudioSegment.from_file(seg["path"])
            duration_ms = len(audio)
            timings.append(
                {"segment_id": seg["segment_id"], "start_ms": current_ms, "end_ms": current_ms + duration_ms}
            )
            current_ms += duration_ms + silence_ms

        return timings
