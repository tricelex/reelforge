"""SpeakerDetectionService — face detection + diarization for smart crop."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, final

logger = logging.getLogger('reelforge.rendering.speaker_detection')


@dataclass(frozen=True)
class SpeakerCropResult:
    """Result of speaker/face detection for smart crop."""

    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float
    face_detected: bool
    speaker_id: str | None = None


@final
class SpeakerDetectionService:
    """MediaPipe face detection + PyAnnote diarization for smart crop.

    Falls back to center crop when face detection fails or is unavailable.
    """

    def __init__(self) -> None:
        """Initialise with an empty detector cache."""
        self._detector_cache: Any = None

    def detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        manual_crop_x: int | None = None,
        manual_crop_y: int | None = None,
        manual_crop_w: int | None = None,
        manual_crop_h: int | None = None,
    ) -> SpeakerCropResult:
        """Return optimal crop coordinates for the speaking region."""
        if all(
            v is not None for v in [manual_crop_x, manual_crop_w, manual_crop_h]
        ):
            return SpeakerCropResult(
                crop_x=manual_crop_x or 0,
                crop_w=manual_crop_w or 1080,
                crop_h=manual_crop_h or 1920,
                confidence=1.0,
                face_detected=True,
            )
        return self._detect_from_video(video_path, start_sec, end_sec)

    def _detect_from_video(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> SpeakerCropResult:
        """Sample frames, detect faces, return median crop.

        Falls back to center crop on any error.
        """
        try:
            return self._mediapipe_detect(video_path, start_sec, end_sec)
        except Exception:
            logger.warning(
                'Face detection failed, falling back to center crop',
                exc_info=True,
            )
            return self._center_fallback()

    def _mediapipe_detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> SpeakerCropResult:
        """Use MediaPipe face detector to find speaker crop coordinates."""
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        cap = cv2.VideoCapture(str(video_path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            crop_w = int(frame_w * 9 / 16)
            crop_w = min(crop_w, frame_w)
            crop_h = frame_w
            detector = self._get_detector()
            start_frame = int(start_sec * fps)
            end_frame = int(end_sec * fps)
            sample_step = max(1, int(fps * 2))
            center_xs: list[float] = []
            for frame_no in range(start_frame, end_frame, sample_step):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                import mediapipe as mp  # noqa: PLC0415

                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb,
                )
                detection_result = detector.detect(image)
                for det in detection_result.detections:
                    bbox = det.bounding_box
                    center_xs.append(bbox.origin_x + bbox.width / 2)
            if not center_xs:
                return self._center_fallback(frame_w)
            median_cx = float(np.median(center_xs))
            crop_x = max(0, int(median_cx - crop_w / 2))
            crop_x = min(crop_x, frame_w - crop_w)
            denom = max(1, (end_frame - start_frame) // sample_step)
            return SpeakerCropResult(
                crop_x=crop_x,
                crop_w=crop_w,
                crop_h=crop_h,
                confidence=len(center_xs) / denom,
                face_detected=True,
            )
        finally:
            cap.release()

    def _center_fallback(self, frame_w: int = 1920) -> SpeakerCropResult:
        """Return a center-crop result when face detection is not possible."""
        crop_w = int(frame_w * 9 / 16)
        crop_x = (frame_w - crop_w) // 2
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_w=crop_w,
            crop_h=frame_w,
            confidence=0.0,
            face_detected=False,
        )

    def _get_detector(self) -> Any:
        """Load MediaPipe face detector from baked or cache path."""
        if self._detector_cache is not None:
            return self._detector_cache

        import os  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415
        from pathlib import Path as ModelPath  # noqa: PLC0415

        from mediapipe.tasks import python as mp_python  # noqa: PLC0415
        from mediapipe.tasks.python import vision  # noqa: PLC0415

        baked = os.environ.get('MEDIAPIPE_FACE_MODEL_PATH', '')
        if baked:
            model_path = ModelPath(baked)
        else:
            model_path = (
                ModelPath.home()
                / '.cache'
                / 'mediapipe'
                / 'blaze_face_short_range.tflite'
            )
        if not model_path.exists():
            model_path.parent.mkdir(parents=True, exist_ok=True)
            url = (
                'https://storage.googleapis.com/mediapipe-models/face_detector'
                '/blaze_face_short_range/float16/latest'
                '/blaze_face_short_range.tflite'
            )
            urllib.request.urlretrieve(url, model_path)
        base_options = mp_python.BaseOptions(
            model_asset_path=str(model_path),
        )
        options = vision.FaceDetectorOptions(base_options=base_options)
        self._detector_cache = vision.FaceDetector.create_from_options(options)
        return self._detector_cache

    def diarize(self, video_path: Path) -> list[dict[str, Any]]:
        """Run PyAnnote speaker diarization.

        Returns [{speaker_id, start, end}] list.
        Raises FatalProviderError when HuggingFace token is missing.
        """
        import subprocess  # noqa: PLC0415, S404
        import tempfile  # noqa: PLC0415
        from pathlib import Path as AudioPath  # noqa: PLC0415

        from django.conf import settings  # noqa: PLC0415

        from server.common.exceptions import FatalProviderError  # noqa: PLC0415

        token: str = getattr(settings, 'HUGGINGFACE_TOKEN', '') or ''
        if not token.strip():
            raise FatalProviderError(
                'HUGGINGFACE_TOKEN is required for speaker diarization',
                provider='pyannote',
                error_code='missing_hf_token',
            )

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            audio_path = tmp.name
        try:
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    'ffmpeg',
                    '-y',
                    '-i',
                    str(video_path),
                    '-ac',
                    '1',
                    '-ar',
                    '16000',
                    '-vn',
                    audio_path,
                ],
                check=True,
                capture_output=True,
            )
            from pyannote.audio import (  # noqa: PLC0415
                Pipeline as PyannotePipeline,
            )

            diarizer = PyannotePipeline.from_pretrained(
                'pyannote/speaker-diarization-community-1',
                token=token,
            )
            annotation = diarizer(audio_path).speaker_diarization
            return [
                {
                    'speaker_id': speaker,
                    'start': turn.start,
                    'end': turn.end,
                }
                for turn, _, speaker in annotation.itertracks(
                    yield_label=True,
                )
            ]
        finally:
            AudioPath(audio_path).unlink(missing_ok=True)
