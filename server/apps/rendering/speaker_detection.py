"""SpeakerDetectionService — face detection + diarization for smart crop."""

import logging
import math
import os
import queue
import threading
import time
from dataclasses import dataclass
from operator import itemgetter
from pathlib import Path
from typing import Any, final

logger = logging.getLogger('reelforge.rendering.speaker_detection')

_DIARIZATION_SAMPLE_RATE = 16000
_diarization_pipeline: Any = None
_diarization_pipeline_lock = threading.Lock()

_DIARIZATION_POOL_SIZE = int(os.environ.get('DIARIZATION_POOL_SIZE', '4'))
_DIARIZATION_CHUNK_S = float(os.environ.get('DIARIZATION_CHUNK_S', '900'))
_DIARIZATION_CHUNK_OVERLAP_S = float(
    os.environ.get('DIARIZATION_CHUNK_OVERLAP_S', '10'),
)
_DIARIZATION_CHUNK_TIMEOUT_S = float(
    os.environ.get('DIARIZATION_CHUNK_TIMEOUT_S', '600'),
)
_diarization_pool: '_DiarizationPool | None' = None
_diarization_pool_lock = threading.Lock()
_DIARIZATION_POOL_WORKER_TORCH_THREADS = os.environ.get(
    'DIARIZATION_POOL_WORKER_TORCH_THREADS',
    '1',
)


def _configure_torch_threads() -> None:
    """Use TORCH_NUM_THREADS (default 4) for CPU inference."""
    import os  # noqa: PLC0415

    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return

    raw = os.environ.get('TORCH_NUM_THREADS', '4').strip() or '4'
    try:
        n_threads = int(raw)
    except ValueError:
        n_threads = 4
    n_threads = max(n_threads, 1)
    torch.set_num_threads(n_threads)


@dataclass(frozen=True)
class ChunkDiarizationResult:
    """One chunk's local diarization output, before global reconciliation."""

    chunk_id: int
    start_offset: float
    segments: list[dict[str, Any]]
    centroids: dict[str, list[float]]


def _get_diarization_pipeline(token: str) -> tuple[Any, bool]:
    """Return cached pyannote pipeline; load once per worker process.

    Note: Pipeline.from_pretrained() only forwards `token`/`cache_dir` to
    the underlying pipeline class — it does not accept arbitrary
    hyperparameter overrides (e.g. batch sizes) as kwargs.
    """
    global _diarization_pipeline  # noqa: PLW0603
    if _diarization_pipeline is not None:
        return _diarization_pipeline, True
    with _diarization_pipeline_lock:
        if _diarization_pipeline is not None:
            return _diarization_pipeline, True
        from pyannote.audio import (  # noqa: PLC0415
            Pipeline as PyannotePipeline,
        )

        _configure_torch_threads()
        started = time.perf_counter()
        _diarization_pipeline = PyannotePipeline.from_pretrained(
            'pyannote/speaker-diarization-community-1',
            token=token,
        )
        logger.info(
            'diarization_pipeline_loaded elapsed_s=%.2f',
            time.perf_counter() - started,
        )
        return _diarization_pipeline, False


def _diarize_chunk_file(
    wav_path: str,
    token: str,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Diarize one chunk's audio file; returns (segments, local centroids)."""
    pipeline, _cached = _get_diarization_pipeline(token)
    audio_in_memory = _load_diarization_audio(wav_path)
    started = time.perf_counter()
    output = pipeline(audio_in_memory)
    segments = [
        {'speaker_id': speaker, 'start': turn.start, 'end': turn.end}
        for turn, speaker in output.speaker_diarization
    ]
    labels = output.speaker_diarization.labels()
    embeddings = output.speaker_embeddings
    centroids = {
        label: list(embeddings[i]) for i, label in enumerate(labels)
    }
    logger.info(
        'diarization_chunk_complete segment_count=%d elapsed_s=%.2f',
        len(segments),
        time.perf_counter() - started,
    )
    return segments, centroids


def _pool_worker_main(
    input_queue: Any,
    output_queue: Any,
    hf_token: str,
) -> None:
    """Entry point for a persistent diarization pool worker process.

    Loops on `input_queue` for `(chunk_id, wav_path, start_offset)` jobs
    until it receives the `None` shutdown sentinel. The pyannote pipeline
    loads once (cached module-level, per-process) on the first job.

    Overrides TORCH_NUM_THREADS for this process only — one chunk per
    pool worker at a time means N processes should each use a fraction of
    the container's CPUs, not the container-wide thread count.
    """
    os.environ['TORCH_NUM_THREADS'] = _DIARIZATION_POOL_WORKER_TORCH_THREADS
    while True:
        job = input_queue.get()
        if job is None:
            return
        chunk_id, wav_path, _start_offset = job
        try:
            segments, centroids = _diarize_chunk_file(wav_path, hf_token)
        except Exception as exc:
            output_queue.put((chunk_id, 'error', str(exc), None))
            continue
        output_queue.put((chunk_id, 'ok', segments, centroids))


@dataclass
class _PoolSlot:
    """One pool worker: its process handle plus its input/output queues."""

    process: Any
    input_queue: Any
    output_queue: Any


class _DiarizationPool:
    """Persistent, killable pool of diarization worker processes.

    Each chunk is submitted to a slot round-robin; a slot that doesn't
    respond within `timeout_s` is killed and replaced so CPU is reclaimed
    immediately instead of the job running to completion for nothing.
    """

    def __init__(
        self,
        pool_size: int,
        hf_token: str,
        *,
        mp_context: Any = None,
    ) -> None:
        import multiprocessing  # noqa: PLC0415

        self._pool_size = pool_size
        self._hf_token = hf_token
        self._ctx = mp_context or multiprocessing.get_context('spawn')
        self._slots = [self._spawn_slot() for _ in range(pool_size)]
        self._next_slot = 0

    def _spawn_slot(self) -> _PoolSlot:
        input_queue = self._ctx.Queue()
        output_queue = self._ctx.Queue()
        process = self._ctx.Process(
            target=_pool_worker_main,
            args=(input_queue, output_queue, self._hf_token),
            daemon=True,
        )
        process.start()
        return _PoolSlot(process, input_queue, output_queue)

    def submit_chunk(
        self,
        chunk_id: int,
        wav_path: str,
        start_offset: float,
        timeout_s: float,
    ) -> ChunkDiarizationResult:
        """Run one chunk on the next slot; kill+replace that slot on timeout."""
        slot_idx = self._next_slot
        self._next_slot = (self._next_slot + 1) % self._pool_size
        slot = self._slots[slot_idx]
        slot.input_queue.put((chunk_id, wav_path, start_offset))

        try:
            result = slot.output_queue.get(timeout=timeout_s)
        except queue.Empty:
            self._replace_slot(slot_idx)
            msg = f'Diarization chunk {chunk_id} exceeded {timeout_s}s'
            raise TimeoutError(msg) from None

        _chunk_id, status, payload, centroids = result
        if status == 'error':
            msg = f'Diarization chunk {chunk_id} failed: {payload}'
            raise RuntimeError(msg)
        return ChunkDiarizationResult(
            chunk_id=chunk_id,
            start_offset=start_offset,
            segments=payload,
            centroids=centroids,
        )

    def _replace_slot(self, slot_idx: int) -> None:
        slot = self._slots[slot_idx]
        slot.process.terminate()
        slot.process.join(timeout=5.0)
        if slot.process.is_alive():
            slot.process.kill()
            slot.process.join()
        self._slots[slot_idx] = self._spawn_slot()


def _get_diarization_pool(token: str) -> '_DiarizationPool':
    """Return the shared pool, starting it (once) on first use."""
    global _diarization_pool  # noqa: PLW0603
    if _diarization_pool is not None:
        return _diarization_pool
    with _diarization_pool_lock:
        if _diarization_pool is None:
            _diarization_pool = _DiarizationPool(
                pool_size=_DIARIZATION_POOL_SIZE,
                hf_token=token,
            )
        return _diarization_pool


def preload_diarization_pool() -> bool:
    """Eager-start the diarization pool when DIARIZATION_PRELOAD=1.

    Worker only. Returns True if the pool is running. Soft-fails (logs,
    returns False) when the token is missing or ML deps are unavailable.
    """
    flag = os.environ.get('DIARIZATION_PRELOAD', '').strip().lower()
    if flag not in {'1', 'true', 'yes'}:
        return False
    try:
        from django.conf import settings  # noqa: PLC0415
    except Exception:
        logger.warning('diarization_preload_skipped reason=django_unavailable')
        return False
    token: str = getattr(settings, 'HUGGINGFACE_TOKEN', '') or ''
    if not token.strip():
        logger.warning('diarization_preload_skipped reason=missing_hf_token')
        return False
    try:
        _get_diarization_pool(token)
    except Exception:
        logger.exception('diarization_preload_failed')
        return False
    else:
        logger.info(
            'diarization_pool_started pool_size=%d',
            _DIARIZATION_POOL_SIZE,
        )
        return True


def _probe_audio_duration_s(audio_path: str) -> float:
    """Return audio duration in seconds by reading the file header only."""
    import torchaudio  # noqa: PLC0415

    info = torchaudio.info(audio_path)
    return float(info.num_frames) / float(info.sample_rate)


def _chunk_time_ranges(
    duration_s: float,
    chunk_s: float,
    overlap_s: float,
) -> list[tuple[float, float]]:
    """Split [0, duration_s] into overlapping (start, end) windows."""
    if duration_s <= 0:
        msg = f'duration_s must be positive, got {duration_s}'
        raise ValueError(msg)
    if overlap_s >= chunk_s:
        msg = f'overlap_s ({overlap_s}) must be less than chunk_s ({chunk_s})'
        raise ValueError(msg)

    step = chunk_s - overlap_s
    ranges: list[tuple[float, float]] = []
    start = 0.0
    while True:
        end = min(start + chunk_s, duration_s)
        ranges.append((start, end))
        if end >= duration_s:
            return ranges
        start += step


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


@dataclass
class _SpeakerClusters:
    """Running centroid clusters accumulated across chunks."""

    sums: list[list[float]]
    counts: list[int]
    labels: list[str]

    def assign(self, centroid: list[float], threshold: float) -> str:
        """Assign to the closest cluster above threshold, or start a new one."""
        best_idx = -1
        best_sim = threshold
        for idx, count in enumerate(self.counts):
            representative = [s / count for s in self.sums[idx]]
            sim = _cosine_similarity(centroid, representative)
            if sim >= best_sim:
                best_sim = sim
                best_idx = idx

        if best_idx == -1:
            self.sums.append(list(centroid))
            self.counts.append(1)
            self.labels.append(f'SPEAKER_{len(self.labels):02d}')
            return self.labels[-1]

        self.sums[best_idx] = [
            s + c for s, c in zip(self.sums[best_idx], centroid, strict=True)
        ]
        self.counts[best_idx] += 1
        return self.labels[best_idx]


def _reconcile_speakers(
    chunk_results: list[ChunkDiarizationResult],
    similarity_threshold: float = 0.75,
) -> list[dict[str, Any]]:
    """Merge per-chunk local speaker labels into globally consistent ids.

    Greedily assigns each chunk's speaker centroid to the closest existing
    global cluster (by cosine similarity) or starts a new one, then remaps
    segments to global ids with absolute (chunk-offset-adjusted) timestamps.
    """
    clusters = _SpeakerClusters(sums=[], counts=[], labels=[])
    reconciled: list[dict[str, Any]] = []

    for chunk in chunk_results:
        local_to_global = {
            local_label: clusters.assign(
                chunk.centroids[local_label],
                similarity_threshold,
            )
            for local_label in sorted(chunk.centroids)
        }
        reconciled.extend(
            {
                'speaker_id': local_to_global[seg['speaker_id']],
                'start': seg['start'] + chunk.start_offset,
                'end': seg['end'] + chunk.start_offset,
            }
            for seg in chunk.segments
        )

    reconciled.sort(key=itemgetter('start'))
    return reconciled


def _load_diarization_audio(audio_path: str) -> dict[str, Any]:
    """Load mono 16 kHz WAV for pyannote (bypasses torchcodec file decoding)."""
    import torchaudio  # noqa: PLC0415

    waveform, sample_rate = torchaudio.load(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sample_rate != _DIARIZATION_SAMPLE_RATE:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            _DIARIZATION_SAMPLE_RATE,
        )
        sample_rate = _DIARIZATION_SAMPLE_RATE
    return {'waveform': waveform, 'sample_rate': sample_rate}


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
        """Run chunked, pooled PyAnnote speaker diarization.

        Splits the source audio into fixed-duration chunks, diarizes each
        on a persistent worker pool (bounding worst-case time per chunk and
        reclaiming CPU immediately if a chunk times out), then reconciles
        per-chunk local speaker labels into globally consistent ids.

        Returns [{speaker_id, start, end}] list, absolute to the source.
        Raises FatalProviderError when the HuggingFace token is missing or
        a chunk exceeds its timeout.
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
        chunk_paths: list[str] = []
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
            duration_s = _probe_audio_duration_s(audio_path)
            ranges = _chunk_time_ranges(
                duration_s,
                _DIARIZATION_CHUNK_S,
                _DIARIZATION_CHUNK_OVERLAP_S,
            )
            pool = _get_diarization_pool(token)
            chunk_results: list[ChunkDiarizationResult] = []
            for chunk_id, (start, end) in enumerate(ranges):
                chunk_path = f'{audio_path}.chunk{chunk_id}.wav'
                subprocess.run(  # noqa: S603
                    [  # noqa: S607
                        'ffmpeg',
                        '-y',
                        '-ss',
                        f'{start:.3f}',
                        '-to',
                        f'{end:.3f}',
                        '-i',
                        audio_path,
                        '-ac',
                        '1',
                        '-ar',
                        '16000',
                        chunk_path,
                    ],
                    check=True,
                    capture_output=True,
                )
                chunk_paths.append(chunk_path)
                try:
                    chunk_results.append(
                        pool.submit_chunk(
                            chunk_id=chunk_id,
                            wav_path=chunk_path,
                            start_offset=start,
                            timeout_s=_DIARIZATION_CHUNK_TIMEOUT_S,
                        ),
                    )
                except TimeoutError as exc:
                    raise FatalProviderError(
                        str(exc),
                        provider='pyannote',
                        error_code='diarization_chunk_timeout',
                    ) from exc

            segments = _reconcile_speakers(chunk_results)
            logger.info(
                'diarization_complete segment_count=%d chunk_count=%d',
                len(segments),
                len(chunk_results),
            )
            return segments
        finally:
            AudioPath(audio_path).unlink(missing_ok=True)
            for chunk_path in chunk_paths:
                AudioPath(chunk_path).unlink(missing_ok=True)
