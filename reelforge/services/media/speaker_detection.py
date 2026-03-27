from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("***REMOVED***.media.speaker_detection")


@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float  # fraction of sampled frames where a face was detected
    face_detected: bool  # False means fell back to center crop


class SpeakerDetectionService:
    """Detects speaker position in a video clip and returns a stable 9:16 crop window.

    Uses OpenCV's built-in Haar cascade face detector, sampling every N frames for
    efficiency. Returns the median face X position across sampled frames to avoid jitter.
    Falls back to center crop when no face is detected.
    """

    def __init__(self, sample_every_n_frames: int = 5) -> None:
        self.sample_every_n_frames = sample_every_n_frames

    def detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> SpeakerCropResult:
        import cv2

        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        crop_w = int(9 / 16 * src_h)
        crop_h = src_h
        center_x = max(0, (src_w - crop_w) // 2)

        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        face_x_positions: list[float] = []
        total_sampled = 0
        frame_idx = start_frame

        while cap.isOpened() and frame_idx <= end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            if (frame_idx - start_frame) % self.sample_every_n_frames == 0:
                total_sampled += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
                )
                if len(faces) > 0:
                    x, y, w, h = faces[0]
                    face_center_x = float(x + w / 2)
                    face_x_positions.append(face_center_x)
            frame_idx += 1

        cap.release()

        if not face_x_positions:
            logger.info(
                "No face detected — falling back to center crop",
                extra={"video_path": str(video_path), "total_sampled": total_sampled},
            )
            return SpeakerCropResult(
                crop_x=center_x,
                crop_w=crop_w,
                crop_h=crop_h,
                confidence=0.0,
                face_detected=False,
            )

        median_face_x = statistics.median(face_x_positions)
        crop_x = int(median_face_x) - crop_w // 2
        crop_x = max(0, min(crop_x, src_w - crop_w))
        confidence = len(face_x_positions) / total_sampled if total_sampled > 0 else 0.0

        logger.info(
            "Speaker detected",
            extra={
                "video_path": str(video_path),
                "median_face_x": median_face_x,
                "crop_x": crop_x,
                "confidence": confidence,
                "frames_sampled": total_sampled,
                "faces_found": len(face_x_positions),
            },
        )
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_w=crop_w,
            crop_h=crop_h,
            confidence=confidence,
            face_detected=True,
        )
