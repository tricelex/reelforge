from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("***REMOVED***.media.speaker_detection")


@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float  # fraction of sampled frames where a face was detected
    face_detected: bool  # False means fell back to center crop
    speaker_id: str | None = None


@dataclass
class DiarizationSegment:
    speaker_id: str
    start: float
    end: float


class SpeakerDetectionService:
    """Speaker detection using MediaPipe face detection + PyAnnote diarization.

    Replaces the legacy OpenCV Haar cascade implementation.
    Lazy-loads models to avoid import-time overhead in workers.
    """

    def __init__(self) -> None:
        self._face_detector: Any = None
        self._diarizer: Any = None

    def _get_face_detector(self) -> Any:
        if self._face_detector is None:
            import mediapipe as mp

            self._face_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.5,
            )
        return self._face_detector

    def _get_diarizer(self) -> Any:
        if self._diarizer is None:
            from django.conf import settings
            from pyannote.audio import Pipeline as PyannotePipeline

            self._diarizer = PyannotePipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=settings.HUGGINGFACE_TOKEN,
            )
        return self._diarizer

    def diarize(self, video_path: str | Path) -> list[DiarizationSegment]:
        """Run full speaker diarization on the audio of a video file.

        Extracts audio to a temp WAV, runs PyAnnote, returns segment list.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = tmp.name

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-vn",
                    audio_path,
                ],
                check=True,
                capture_output=True,
            )
            diarizer = self._get_diarizer()
            diarization = diarizer(audio_path)
            segments: list[DiarizationSegment] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(speaker_id=speaker, start=turn.start, end=turn.end)
                )
            return segments
        except subprocess.CalledProcessError as exc:
            logger.error(
                "ffmpeg audio extraction failed",
                extra={"video_path": str(video_path), "returncode": exc.returncode},
            )
            raise
        finally:
            Path(audio_path).unlink(missing_ok=True)

    def detect_faces_for_segment(
        self,
        video_path: str | Path,
        start_sec: float,
        end_sec: float,
        sample_every_n_frames: int = 5,
    ) -> list[dict]:
        """Sample frames in [start_sec, end_sec] and return face bboxes per timestamp."""
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            start_frame = int(start_sec * fps)
            end_frame = int(end_sec * fps)
            detector = self._get_face_detector()
            results: list[dict] = []

            for frame_num in range(start_frame, end_frame, sample_every_n_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    break
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detection = detector.process(frame_rgb)
                timestamp = frame_num / fps
                faces: list[dict] = []
                if detection.detections:
                    for d in detection.detections:
                        bbox = d.location_data.relative_bounding_box
                        faces.append(
                            {
                                "x": int(bbox.xmin * frame_width),
                                "y": int(bbox.ymin * frame_height),
                                "w": int(bbox.width * frame_width),
                                "h": int(bbox.height * frame_height),
                                "confidence": float(d.score[0]),
                            }
                        )
                results.append({"timestamp": timestamp, "faces": faces})
        finally:
            cap.release()
        return results

    def detect(
        self,
        video_path: Path | str,
        start_sec: float,
        end_sec: float,
        manual_crop_x: int | None = None,
        manual_crop_y: int | None = None,
        manual_crop_w: int | None = None,
        manual_crop_h: int | None = None,
    ) -> SpeakerCropResult:
        """Primary method called from TrimAndCropStage for SMART_CROP mode.

        If all manual_crop_* are set, returns those coords directly (operator override).
        Otherwise uses MediaPipe face detection to find the dominant speaker position.
        Falls back to centre crop when no face is detected.
        """
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        try:
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()

        # Manual crop override — operator sets exact pixel coordinates
        if all(
            v is not None
            for v in [manual_crop_x, manual_crop_y, manual_crop_w, manual_crop_h]
        ):
            return SpeakerCropResult(
                crop_x=int(manual_crop_x),
                crop_w=int(manual_crop_w),
                crop_h=int(manual_crop_h),
                confidence=1.0,
                face_detected=True,
            )

        face_data = self.detect_faces_for_segment(str(video_path), start_sec, end_sec)
        face_centers_x: list[int] = []
        total_samples = len(face_data)
        samples_with_face = 0

        for sample in face_data:
            if sample["faces"]:
                samples_with_face += 1
                best = max(sample["faces"], key=lambda f: f["confidence"])
                face_centers_x.append(best["x"] + best["w"] // 2)

        crop_w = int(frame_height * 9 / 16)

        if not face_centers_x:
            logger.info(
                "No face detected — falling back to center crop",
                extra={"video_path": str(video_path), "total_sampled": total_samples},
            )
            crop_x = max(0, (frame_width - crop_w) // 2)
            return SpeakerCropResult(
                crop_x=crop_x,
                crop_w=crop_w,
                crop_h=frame_height,
                confidence=0.0,
                face_detected=False,
            )

        median_x = int(np.median(face_centers_x))
        crop_x = median_x - crop_w // 2
        crop_x = max(0, min(crop_x, frame_width - crop_w))
        confidence = samples_with_face / total_samples if total_samples > 0 else 0.0

        logger.info(
            "Speaker detected via MediaPipe",
            extra={
                "video_path": str(video_path),
                "median_face_x": median_x,
                "crop_x": crop_x,
                "confidence": confidence,
            },
        )
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_w=crop_w,
            crop_h=frame_height,
            confidence=confidence,
            face_detected=True,
        )
