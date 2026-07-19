"""SpeakerDetectionService — face detection for smart crop."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, final

logger = logging.getLogger('reelforge.rendering.speaker_detection')


def _crop_window(
    frame_w: int,
    frame_h: int,
    *,
    target_width: int,
    target_height: int,
) -> tuple[int, int]:
    """Return the largest (crop_w, crop_h) matching the target aspect."""
    crop_w = min(frame_w, int(frame_h * target_width / target_height))
    crop_h = min(frame_h, int(frame_w * target_height / target_width))
    return max(1, crop_w), max(1, crop_h)


def clamp_crop_rect(
    crop_x: int,
    crop_y: int,
    crop_w: int,
    crop_h: int,
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    """Clamp a crop rect into the source frame.

    Returns None when the frame size is invalid.
    """
    if frame_w <= 0 or frame_h <= 0:
        return None
    clamped_w = min(max(1, crop_w), frame_w)
    clamped_h = min(max(1, crop_h), frame_h)
    clamped_x = max(0, min(crop_x, frame_w - clamped_w))
    clamped_y = max(0, min(crop_y, frame_h - clamped_h))
    return clamped_x, clamped_y, clamped_w, clamped_h


@dataclass(frozen=True)
class SpeakerCropResult:
    """Result of speaker/face detection for smart crop."""

    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float
    face_detected: bool
    crop_y: int = 0
    speaker_id: str | None = None


@final
class SpeakerDetectionService:
    """MediaPipe face detection for smart crop.

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
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> SpeakerCropResult:
        """Return optimal crop coordinates for the speaking region.

        ``target_width``/``target_height`` define the output aspect ratio
        the crop window must match (only their ratio is used).
        """
        if all(
            v is not None for v in [manual_crop_x, manual_crop_w, manual_crop_h]
        ):
            return self._manual_crop_result(
                video_path,
                crop_x=manual_crop_x or 0,
                crop_y=manual_crop_y or 0,
                crop_w=manual_crop_w or target_width,
                crop_h=manual_crop_h or target_height,
                target_width=target_width,
                target_height=target_height,
            )
        return self._detect_from_video(
            video_path,
            start_sec,
            end_sec,
            target_width=target_width,
            target_height=target_height,
        )

    def _manual_crop_result(
        self,
        video_path: Path,
        *,
        crop_x: int,
        crop_y: int,
        crop_w: int,
        crop_h: int,
        target_width: int,
        target_height: int,
    ) -> SpeakerCropResult:
        """Return a manual crop, clamped to the source frame when known."""
        frame_w, frame_h = self._probe_frame_size(video_path)
        if frame_w is not None and frame_h is not None:
            clamped = clamp_crop_rect(
                crop_x,
                crop_y,
                crop_w,
                crop_h,
                frame_w,
                frame_h,
            )
            if clamped is None:
                return self._center_fallback(
                    frame_w,
                    frame_h,
                    target_width=target_width,
                    target_height=target_height,
                )
            crop_x, crop_y, crop_w, crop_h = clamped
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_y=crop_y,
            crop_w=crop_w,
            crop_h=crop_h,
            confidence=1.0,
            face_detected=True,
        )

    def _detect_from_video(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        *,
        target_width: int,
        target_height: int,
    ) -> SpeakerCropResult:
        """Sample frames, detect faces, return median crop.

        Falls back to center crop on any error.
        """
        try:
            return self._mediapipe_detect(
                video_path,
                start_sec,
                end_sec,
                target_width=target_width,
                target_height=target_height,
            )
        except Exception:
            logger.warning(
                'Face detection failed, falling back to center crop',
                exc_info=True,
            )
            return self._fallback_for_path(
                video_path,
                target_width=target_width,
                target_height=target_height,
            )

    def _fallback_for_path(
        self,
        video_path: Path,
        *,
        target_width: int,
        target_height: int,
    ) -> SpeakerCropResult:
        """Center-crop using probed source dimensions when possible."""
        frame_w, frame_h = self._probe_frame_size(video_path)
        if frame_w is None or frame_h is None:
            logger.warning(
                'Could not probe source dimensions for %s; '
                'using 1920x1080 fallback',
                video_path,
            )
            frame_w, frame_h = 1920, 1080
        return self._center_fallback(
            frame_w,
            frame_h,
            target_width=target_width,
            target_height=target_height,
        )

    def _probe_frame_size(
        self,
        video_path: Path,
    ) -> tuple[int | None, int | None]:
        """Return source (width, height) via ffprobe, then OpenCV."""
        from server.apps.rendering.clip_stages.probe import (  # noqa: PLC0415
            sync_ffprobe_dimensions,
        )

        width, height = sync_ffprobe_dimensions(str(video_path))
        if width is not None and height is not None:
            return width, height
        return self._opencv_frame_size(video_path)

    def _opencv_frame_size(
        self,
        video_path: Path,
    ) -> tuple[int | None, int | None]:
        """Return frame size via OpenCV, or (None, None) on failure."""
        try:
            import cv2  # noqa: PLC0415
        except Exception:
            logger.debug('OpenCV unavailable for probe', exc_info=True)
            return None, None
        return self._read_opencv_capture_size(cv2, video_path)

    def _read_opencv_capture_size(
        self,
        cv2: Any,
        video_path: Path,
    ) -> tuple[int | None, int | None]:
        """Read width/height from an OpenCV VideoCapture."""
        try:
            cap = cv2.VideoCapture(str(video_path))
        except Exception:
            logger.debug(
                'OpenCV probe failed for %s',
                video_path,
                exc_info=True,
            )
            return None, None
        try:
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()
        if frame_w > 0 and frame_h > 0:
            return frame_w, frame_h
        return None, None

    def _mediapipe_detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        *,
        target_width: int,
        target_height: int,
    ) -> SpeakerCropResult:
        """Use MediaPipe face detector to find speaker crop coordinates."""
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        cap = cv2.VideoCapture(str(video_path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            crop_w, crop_h = _crop_window(
                frame_w,
                frame_h,
                target_width=target_width,
                target_height=target_height,
            )
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
                return self._center_fallback(
                    frame_w,
                    frame_h,
                    target_width=target_width,
                    target_height=target_height,
                )
            median_cx = float(np.median(center_xs))
            crop_x = max(0, int(median_cx - crop_w / 2))
            crop_x = min(crop_x, frame_w - crop_w)
            denom = max(1, (end_frame - start_frame) // sample_step)
            return SpeakerCropResult(
                crop_x=crop_x,
                crop_y=(frame_h - crop_h) // 2,
                crop_w=crop_w,
                crop_h=crop_h,
                confidence=len(center_xs) / denom,
                face_detected=True,
            )
        finally:
            cap.release()

    def _center_fallback(
        self,
        frame_w: int = 1920,
        frame_h: int = 1080,
        *,
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> SpeakerCropResult:
        """Return a center-crop result when face detection is not possible."""
        crop_w, crop_h = _crop_window(
            frame_w,
            frame_h,
            target_width=target_width,
            target_height=target_height,
        )
        crop_x = (frame_w - crop_w) // 2
        crop_y = (frame_h - crop_h) // 2
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_y=crop_y,
            crop_w=crop_w,
            crop_h=crop_h,
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
