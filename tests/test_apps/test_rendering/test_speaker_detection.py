"""Tests for SpeakerDetectionService."""

import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering import speaker_detection as speaker_detection_module
from server.apps.rendering.speaker_detection import (
    SpeakerCropResult,
    SpeakerDetectionService,
    preload_diarization_pool,
)


def _reset_diarization_pipeline_cache() -> None:
    speaker_detection_module._diarization_pipeline = None


def test_detect_with_manual_crop() -> None:
    svc = SpeakerDetectionService()
    result = svc.detect(
        video_path=Path('/fake.mp4'),
        start_sec=0.0,
        end_sec=60.0,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=540,
        manual_crop_h=960,
    )
    assert result.face_detected is True
    assert result.confidence == 1.0
    assert result.crop_x == 100


def test_detect_falls_back_to_center_on_error() -> None:
    svc = SpeakerDetectionService()
    with patch.object(
        svc,
        '_mediapipe_detect',
        side_effect=RuntimeError('no mediapipe'),
    ):
        result = svc._detect_from_video(Path('/fake.mp4'), 0.0, 60.0)
    assert result.face_detected is False
    assert result.confidence == 0.0


def test_center_fallback_default() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback()
    assert result.face_detected is False
    assert result.crop_x + result.crop_w <= 1920


def test_center_fallback_custom_width() -> None:
    svc = SpeakerDetectionService()
    result = svc._center_fallback(frame_w=1280)
    assert result.crop_w == int(1280 * 9 / 16)


def test_speaker_crop_result_is_frozen() -> None:
    import pytest

    result = SpeakerCropResult(
        crop_x=0,
        crop_w=540,
        crop_h=960,
        confidence=1.0,
        face_detected=True,
    )
    with pytest.raises(Exception):
        result.crop_x = 100  # type: ignore[misc]


def test_detect_without_manual_crop_falls_back_on_error() -> None:
    svc = SpeakerDetectionService()
    with patch.object(
        svc,
        '_mediapipe_detect',
        side_effect=RuntimeError('no cv2'),
    ):
        result = svc.detect(
            video_path=Path('/fake.mp4'),
            start_sec=0.0,
            end_sec=60.0,
        )
    assert result.face_detected is False


def test_mediapipe_detect_with_no_faces() -> None:
    svc = SpeakerDetectionService()

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cap.get.side_effect = [30.0, 1920]
    mock_cap.read.return_value = (False, None)

    mock_np = MagicMock()
    mock_mp = MagicMock()
    detection_result = MagicMock()
    detection_result.detections = []
    mock_mp.Image.return_value = MagicMock()

    with (
        patch.dict(
            sys.modules,
            {
                'cv2': mock_cv2,
                'numpy': mock_np,
                'mediapipe': mock_mp,
            },
        ),
        patch.object(svc, '_get_detector', return_value=MagicMock()),
    ):
        result = svc._mediapipe_detect(Path('/fake.mp4'), 0.0, 30.0)

    assert result.face_detected is False
    assert result.confidence == 0.0


def test_mediapipe_detect_with_faces() -> None:
    svc = SpeakerDetectionService()

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cap.get.side_effect = [30.0, 1920]
    mock_cap.read.side_effect = [(True, MagicMock()), (False, None)]
    mock_cv2.cvtColor.return_value = MagicMock()

    bbox = MagicMock()
    bbox.origin_x = 800
    bbox.width = 320
    det = MagicMock()
    det.bounding_box = bbox
    mock_detection_result = MagicMock()
    mock_detection_result.detections = [det]
    mock_detector = MagicMock()
    mock_detector.detect.return_value = mock_detection_result

    mock_np = MagicMock()
    mock_np.median.return_value = 960.0
    mock_mp = MagicMock()

    with (
        patch.dict(
            sys.modules,
            {
                'cv2': mock_cv2,
                'numpy': mock_np,
                'mediapipe': mock_mp,
            },
        ),
        patch.object(svc, '_get_detector', return_value=mock_detector),
    ):
        result = svc._mediapipe_detect(Path('/fake.mp4'), 0.0, 1.0)

    assert result.face_detected is True
    assert result.crop_w > 0


def test_get_detector_uses_cache() -> None:
    svc = SpeakerDetectionService()
    cached = MagicMock()
    svc._detector_cache = cached
    assert svc._get_detector() is cached


def test_get_detector_loads_model(tmp_path: Path) -> None:
    svc = SpeakerDetectionService()
    mock_vision = MagicMock()
    mock_mp_python = MagicMock()
    # Pre-create the model file so exists() returns True (no download path)
    model_dir = tmp_path / '.cache' / 'mediapipe'
    model_dir.mkdir(parents=True)
    (model_dir / 'blaze_face_short_range.tflite').write_bytes(b'fake')

    with (
        patch.dict(
            sys.modules,
            {
                'mediapipe.tasks': MagicMock(),
                'mediapipe.tasks.python': mock_mp_python,
                'mediapipe.tasks.python.vision': mock_vision,
                'urllib.request': MagicMock(),
            },
        ),
        patch('pathlib.Path.home', return_value=tmp_path),
    ):
        svc._get_detector()

    assert svc._detector_cache is not None


def test_get_detector_downloads_model_when_missing(tmp_path: Path) -> None:
    svc = SpeakerDetectionService()
    mock_vision = MagicMock()
    mock_mp_python = MagicMock()
    # Do NOT create the model file — exists() will return False

    with (
        patch.dict(
            sys.modules,
            {
                'mediapipe.tasks': MagicMock(),
                'mediapipe.tasks.python': mock_mp_python,
                'mediapipe.tasks.python.vision': mock_vision,
            },
        ),
        patch('pathlib.Path.home', return_value=tmp_path),
        patch('urllib.request.urlretrieve') as mock_urlretrieve,
    ):
        svc._get_detector()

    assert mock_urlretrieve.called
    assert svc._detector_cache is not None


def test_diarize_requires_huggingface_token() -> None:
    svc = SpeakerDetectionService()
    with patch(
        'django.conf.settings.HUGGINGFACE_TOKEN',
        '',
        create=True,
    ):
        try:
            svc.diarize(Path('/fake.mp4'))
            raise AssertionError('expected FatalProviderError')
        except Exception as exc:
            from server.common.exceptions import FatalProviderError

            assert isinstance(exc, FatalProviderError)
            assert exc.error_code == 'missing_hf_token'


def test_chunk_time_ranges_single_chunk_when_duration_fits() -> None:
    from server.apps.rendering.speaker_detection import _chunk_time_ranges

    assert _chunk_time_ranges(300.0, chunk_s=900.0, overlap_s=10.0) == [
        (0.0, 300.0),
    ]


def test_chunk_time_ranges_splits_long_duration() -> None:
    from server.apps.rendering.speaker_detection import _chunk_time_ranges

    assert _chunk_time_ranges(1000.0, chunk_s=400.0, overlap_s=0.0) == [
        (0.0, 400.0),
        (400.0, 800.0),
        (800.0, 1000.0),
    ]


def test_chunk_time_ranges_applies_overlap() -> None:
    from server.apps.rendering.speaker_detection import _chunk_time_ranges

    assert _chunk_time_ranges(1000.0, chunk_s=400.0, overlap_s=50.0) == [
        (0.0, 400.0),
        (350.0, 750.0),
        (700.0, 1000.0),
    ]


def test_chunk_time_ranges_rejects_non_positive_duration() -> None:
    from server.apps.rendering.speaker_detection import _chunk_time_ranges

    with pytest.raises(ValueError, match='duration'):
        _chunk_time_ranges(0.0, chunk_s=400.0, overlap_s=0.0)


def test_chunk_time_ranges_rejects_overlap_not_less_than_chunk() -> None:
    from server.apps.rendering.speaker_detection import _chunk_time_ranges

    with pytest.raises(ValueError, match='overlap'):
        _chunk_time_ranges(1000.0, chunk_s=400.0, overlap_s=400.0)


def test_reconcile_speakers_merges_same_speaker_across_chunks() -> None:
    from server.apps.rendering.speaker_detection import (
        ChunkDiarizationResult,
        _reconcile_speakers,
    )

    chunk0 = ChunkDiarizationResult(
        chunk_id=0,
        start_offset=0.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}],
        centroids={'SPEAKER_00': [1.0, 0.0, 0.0]},
    )
    chunk1 = ChunkDiarizationResult(
        chunk_id=1,
        start_offset=100.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 2.0, 'end': 8.0}],
        centroids={'SPEAKER_00': [0.99, 0.01, 0.0]},
    )

    result = _reconcile_speakers([chunk0, chunk1])

    assert len(result) == 2
    assert result[0]['speaker_id'] == result[1]['speaker_id']
    assert result[0]['start'] == 0.0
    assert result[0]['end'] == 5.0
    assert result[1]['start'] == 102.0
    assert result[1]['end'] == 108.0


def test_reconcile_speakers_keeps_distinct_speakers_separate() -> None:
    from server.apps.rendering.speaker_detection import (
        ChunkDiarizationResult,
        _reconcile_speakers,
    )

    chunk0 = ChunkDiarizationResult(
        chunk_id=0,
        start_offset=0.0,
        segments=[
            {'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0},
            {'speaker_id': 'SPEAKER_01', 'start': 5.0, 'end': 10.0},
        ],
        centroids={
            'SPEAKER_00': [1.0, 0.0, 0.0],
            'SPEAKER_01': [0.0, 1.0, 0.0],
        },
    )

    result = _reconcile_speakers([chunk0])

    global_ids = {seg['speaker_id'] for seg in result}
    assert len(global_ids) == 2


def test_reconcile_speakers_orders_output_by_start_time() -> None:
    from server.apps.rendering.speaker_detection import (
        ChunkDiarizationResult,
        _reconcile_speakers,
    )

    later_chunk = ChunkDiarizationResult(
        chunk_id=1,
        start_offset=100.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}],
        centroids={'SPEAKER_00': [1.0, 0.0, 0.0]},
    )
    earlier_chunk = ChunkDiarizationResult(
        chunk_id=0,
        start_offset=0.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}],
        centroids={'SPEAKER_00': [0.0, 1.0, 0.0]},
    )

    result = _reconcile_speakers([later_chunk, earlier_chunk])

    assert [seg['start'] for seg in result] == [0.0, 100.0]


class _FakeAnnotation:
    """Minimal stand-in for pyannote.core.Annotation used in worker tests."""

    def __init__(self, turns: list[tuple[Any, str]]) -> None:
        self._turns = turns

    def __iter__(self) -> Any:
        return iter(self._turns)

    def labels(self) -> list[str]:
        return sorted({label for _, label in self._turns})


def test_pool_worker_main_processes_job_and_returns_segments_and_centroids() -> (
    None
):
    from server.apps.rendering.speaker_detection import _pool_worker_main

    _reset_diarization_pipeline_cache()

    mock_turn = MagicMock(start=0.0, end=5.0)
    mock_output = MagicMock()
    mock_output.speaker_diarization = _FakeAnnotation([(mock_turn, 'SPEAKER_00')])
    mock_output.speaker_embeddings = [[1.0, 0.0, 0.0]]

    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock(return_value=mock_diarizer_instance)
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    input_q: queue.Queue[Any] = queue.Queue()
    output_q: queue.Queue[Any] = queue.Queue()
    input_q.put((0, '/fake/chunk0.wav', 0.0))
    input_q.put(None)

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value={'waveform': MagicMock(), 'sample_rate': 16000},
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
    ):
        from server.apps.rendering.speaker_detection import _pool_worker_main

        _pool_worker_main(input_q, output_q, 'hf-token')

    chunk_id, status, segments, centroids = output_q.get_nowait()
    assert chunk_id == 0
    assert status == 'ok'
    assert segments == [{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}]
    assert centroids == {'SPEAKER_00': [1.0, 0.0, 0.0]}
    mock_pipeline_cls.from_pretrained.assert_called_once_with(
        'pyannote/speaker-diarization-community-1',
        token='hf-token',
    )


def test_pool_worker_main_reuses_cached_pipeline_across_jobs() -> None:
    _reset_diarization_pipeline_cache()

    mock_turn = MagicMock(start=0.0, end=1.0)
    mock_output = MagicMock()
    mock_output.speaker_diarization = _FakeAnnotation([(mock_turn, 'SPEAKER_00')])
    mock_output.speaker_embeddings = [[1.0, 0.0]]

    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock(return_value=mock_diarizer_instance)
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    input_q: queue.Queue[Any] = queue.Queue()
    output_q: queue.Queue[Any] = queue.Queue()
    input_q.put((0, '/fake/chunk0.wav', 0.0))
    input_q.put((1, '/fake/chunk1.wav', 900.0))
    input_q.put(None)

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value={'waveform': MagicMock(), 'sample_rate': 16000},
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
    ):
        from server.apps.rendering.speaker_detection import _pool_worker_main

        _pool_worker_main(input_q, output_q, 'hf-token')

    assert output_q.get_nowait()[0] == 0
    assert output_q.get_nowait()[0] == 1
    mock_pipeline_cls.from_pretrained.assert_called_once()


def test_pool_worker_main_reports_error_for_failed_job() -> None:
    from server.apps.rendering.speaker_detection import _pool_worker_main

    _reset_diarization_pipeline_cache()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = MagicMock()
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    input_q: queue.Queue[Any] = queue.Queue()
    output_q: queue.Queue[Any] = queue.Queue()
    input_q.put((1, '/fake/chunk1.wav', 900.0))
    input_q.put(None)

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            side_effect=RuntimeError('boom'),
        ),
    ):
        _pool_worker_main(input_q, output_q, 'hf-token')

    chunk_id, status, payload, centroids = output_q.get_nowait()
    assert chunk_id == 1
    assert status == 'error'
    assert 'boom' in payload
    assert centroids is None


def test_pool_worker_main_overrides_torch_threads_for_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering.speaker_detection import _pool_worker_main

    _reset_diarization_pipeline_cache()
    monkeypatch.setenv('TORCH_NUM_THREADS', '4')

    mock_turn = MagicMock(start=0.0, end=1.0)
    mock_output = MagicMock()
    mock_output.speaker_diarization = _FakeAnnotation([(mock_turn, 'SPEAKER_00')])
    mock_output.speaker_embeddings = [[1.0, 0.0]]
    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    input_q: queue.Queue[Any] = queue.Queue()
    output_q: queue.Queue[Any] = queue.Queue()
    input_q.put((0, '/fake/chunk0.wav', 0.0))
    input_q.put(None)

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value={'waveform': MagicMock(), 'sample_rate': 16000},
        ),
    ):
        _pool_worker_main(input_q, output_q, 'hf-token')

    assert os.environ['TORCH_NUM_THREADS'] == '1'


class _FakeProcess:
    """Runs the pool-worker target on a thread instead of a real process."""

    def __init__(
        self,
        target: Any,
        args: tuple[Any, ...],
        *,
        hang: bool,
        stubborn: bool = False,
    ) -> None:
        self._target = target
        self._args = args
        self._hang = hang
        self._stubborn = stubborn
        self._thread: threading.Thread | None = None
        self.terminated = False
        self.killed = False

    def start(self) -> None:
        if self._hang:
            return
        self._thread = threading.Thread(target=self._target, args=self._args)
        self._thread.daemon = True
        self._thread.start()

    def is_alive(self) -> bool:
        if self._hang and self._stubborn:
            return not self.killed
        return self._thread is not None and self._thread.is_alive()

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)


class _FakeMpContext:
    """Fake multiprocessing context — real Queues, thread-backed processes."""

    def __init__(
        self,
        *,
        hang_processes: bool = False,
        stubborn: bool = False,
    ) -> None:
        self._hang_processes = hang_processes
        self._stubborn = stubborn
        self.processes: list[_FakeProcess] = []

    def Queue(self) -> 'queue.Queue[Any]':  # noqa: N802 (matches multiprocessing.Queue)
        return queue.Queue()

    def Process(  # noqa: N802 (matches multiprocessing.Process)
        self,
        *,
        target: Any,
        args: tuple[Any, ...],
        daemon: bool = True,
    ) -> _FakeProcess:
        _ = daemon
        proc = _FakeProcess(
            target,
            args,
            hang=self._hang_processes,
            stubborn=self._stubborn,
        )
        self.processes.append(proc)
        return proc


def test_diarization_pool_submit_chunk_returns_result_on_success() -> None:
    from server.apps.rendering.speaker_detection import _DiarizationPool

    _reset_diarization_pipeline_cache()

    mock_turn = MagicMock(start=0.0, end=5.0)
    mock_output = MagicMock()
    mock_output.speaker_diarization = _FakeAnnotation([(mock_turn, 'SPEAKER_00')])
    mock_output.speaker_embeddings = [[1.0, 0.0]]
    mock_diarizer_instance = MagicMock(return_value=mock_output)
    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = mock_diarizer_instance
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    ctx = _FakeMpContext()

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            return_value={'waveform': MagicMock(), 'sample_rate': 16000},
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
    ):
        pool = _DiarizationPool(
            pool_size=1,
            hf_token='hf-token',
            mp_context=ctx,
        )
        result = pool.submit_chunk(
            chunk_id=0,
            wav_path='/fake/chunk0.wav',
            start_offset=100.0,
            timeout_s=5.0,
        )

    assert result.chunk_id == 0
    assert result.start_offset == 100.0
    assert result.segments == [
        {'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0},
    ]
    assert result.centroids == {'SPEAKER_00': [1.0, 0.0]}
    ctx.processes[0].join(timeout=0.01)


def test_diarization_pool_terminates_and_replaces_worker_on_timeout() -> None:
    from server.apps.rendering.speaker_detection import _DiarizationPool

    ctx = _FakeMpContext(hang_processes=True)
    pool = _DiarizationPool(
        pool_size=1,
        hf_token='hf-token',
        mp_context=ctx,
    )
    original_process = ctx.processes[0]

    with pytest.raises(TimeoutError):
        pool.submit_chunk(
            chunk_id=0,
            wav_path='/fake/chunk0.wav',
            start_offset=0.0,
            timeout_s=0.05,
        )

    assert original_process.terminated is True
    assert len(ctx.processes) == 2
    assert ctx.processes[1] is not original_process


def test_diarization_pool_kills_worker_that_wont_terminate() -> None:
    from server.apps.rendering.speaker_detection import _DiarizationPool

    ctx = _FakeMpContext(hang_processes=True, stubborn=True)
    pool = _DiarizationPool(
        pool_size=1,
        hf_token='hf-token',
        mp_context=ctx,
    )
    original_process = ctx.processes[0]

    with pytest.raises(TimeoutError):
        pool.submit_chunk(
            chunk_id=0,
            wav_path='/fake/chunk0.wav',
            start_offset=0.0,
            timeout_s=0.05,
        )

    assert original_process.terminated is True
    assert original_process.killed is True


def test_diarization_pool_raises_runtime_error_on_worker_failure() -> None:
    from server.apps.rendering.speaker_detection import _DiarizationPool

    _reset_diarization_pipeline_cache()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = MagicMock()
    mock_pyannote_audio = MagicMock()
    mock_pyannote_audio.Pipeline = mock_pipeline_cls

    ctx = _FakeMpContext()

    with (
        patch.dict(
            sys.modules,
            {'pyannote': MagicMock(), 'pyannote.audio': mock_pyannote_audio},
        ),
        patch(
            'server.apps.rendering.speaker_detection._configure_torch_threads',
        ),
        patch(
            'server.apps.rendering.speaker_detection._load_diarization_audio',
            side_effect=RuntimeError('boom'),
        ),
    ):
        pool = _DiarizationPool(
            pool_size=1,
            hf_token='hf-token',
            mp_context=ctx,
        )
        with pytest.raises(RuntimeError, match='boom'):
            pool.submit_chunk(
                chunk_id=0,
                wav_path='/fake/chunk0.wav',
                start_offset=0.0,
                timeout_s=5.0,
            )


def test_configure_torch_threads_noop_when_torch_missing() -> None:
    from server.apps.rendering.speaker_detection import _configure_torch_threads

    with patch.dict(sys.modules, {'torch': None}):
        _configure_torch_threads()


def test_configure_torch_threads_uses_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering.speaker_detection import _configure_torch_threads

    monkeypatch.delenv('TORCH_NUM_THREADS', raising=False)
    mock_torch = MagicMock()

    with patch.dict(sys.modules, {'torch': mock_torch}):
        _configure_torch_threads()

    mock_torch.set_num_threads.assert_called_once_with(4)


def test_configure_torch_threads_falls_back_on_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering.speaker_detection import _configure_torch_threads

    monkeypatch.setenv('TORCH_NUM_THREADS', 'not-a-number')
    mock_torch = MagicMock()

    with patch.dict(sys.modules, {'torch': mock_torch}):
        _configure_torch_threads()

    mock_torch.set_num_threads.assert_called_once_with(4)


def test_configure_torch_threads_clamps_below_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering.speaker_detection import _configure_torch_threads

    monkeypatch.setenv('TORCH_NUM_THREADS', '0')
    mock_torch = MagicMock()

    with patch.dict(sys.modules, {'torch': mock_torch}):
        _configure_torch_threads()

    mock_torch.set_num_threads.assert_called_once_with(1)


def test_get_diarization_pipeline_rechecks_cache_after_acquiring_lock() -> None:
    from server.apps.rendering.speaker_detection import (
        _get_diarization_pipeline,
    )

    _reset_diarization_pipeline_cache()
    sentinel = MagicMock()

    class _FakeLockSetsCacheAsSideEffect:
        def __enter__(self) -> '_FakeLockSetsCacheAsSideEffect':
            speaker_detection_module._diarization_pipeline = sentinel
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch.object(
        speaker_detection_module,
        '_diarization_pipeline_lock',
        _FakeLockSetsCacheAsSideEffect(),
    ):
        result, cached = _get_diarization_pipeline('hf-token')

    assert result is sentinel
    assert cached is True
    _reset_diarization_pipeline_cache()


def test_get_diarization_pool_rechecks_cache_after_acquiring_lock() -> None:
    from server.apps.rendering.speaker_detection import _get_diarization_pool

    speaker_detection_module._diarization_pool = None
    sentinel = MagicMock()

    class _FakeLockSetsPoolAsSideEffect:
        def __enter__(self) -> '_FakeLockSetsPoolAsSideEffect':
            speaker_detection_module._diarization_pool = sentinel
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch.object(
        speaker_detection_module,
        '_diarization_pool_lock',
        _FakeLockSetsPoolAsSideEffect(),
    ):
        result = _get_diarization_pool('hf-token')

    assert result is sentinel
    speaker_detection_module._diarization_pool = None


def test_probe_audio_duration_returns_seconds() -> None:
    from server.apps.rendering.speaker_detection import _probe_audio_duration_s

    mock_info = MagicMock(num_frames=32000, sample_rate=16000)
    mock_torchaudio = MagicMock()
    mock_torchaudio.info.return_value = mock_info

    with patch.dict(sys.modules, {'torchaudio': mock_torchaudio}):
        duration = _probe_audio_duration_s('/fake/audio.wav')

    assert duration == 2.0
    mock_torchaudio.info.assert_called_once_with('/fake/audio.wav')


def _patch_diarize_ffmpeg_and_tempfile() -> Any:
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.name = '/tmp/test_audio.wav'
    return mock_ctx


def test_diarize_chunks_and_reconciles_across_pool() -> None:
    from server.apps.rendering.speaker_detection import (
        ChunkDiarizationResult,
        SpeakerDetectionService,
    )

    svc = SpeakerDetectionService()

    chunk0 = ChunkDiarizationResult(
        chunk_id=0,
        start_offset=0.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}],
        centroids={'SPEAKER_00': [1.0, 0.0]},
    )
    chunk1 = ChunkDiarizationResult(
        chunk_id=1,
        start_offset=890.0,
        segments=[{'speaker_id': 'SPEAKER_00', 'start': 0.0, 'end': 5.0}],
        centroids={'SPEAKER_00': [1.0, 0.0]},
    )
    mock_pool = MagicMock()
    mock_pool.submit_chunk.side_effect = [chunk0, chunk1]

    with (
        patch('subprocess.run') as mock_run,
        patch('tempfile.NamedTemporaryFile') as mock_tmp,
        patch(
            'server.apps.rendering.speaker_detection._probe_audio_duration_s',
            return_value=1000.0,
        ),
        patch(
            'server.apps.rendering.speaker_detection._get_diarization_pool',
            return_value=mock_pool,
        ),
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
        patch('pathlib.Path.unlink'),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_tmp.return_value = _patch_diarize_ffmpeg_and_tempfile()

        result = svc.diarize(Path('/fake.mp4'))

    assert mock_pool.submit_chunk.call_count == 2
    assert len(result) == 2
    assert result[0]['start'] == 0.0
    assert result[1]['start'] == 890.0


def test_diarize_converts_chunk_timeout_to_fatal_provider_error() -> None:
    from server.apps.rendering.speaker_detection import SpeakerDetectionService
    from server.common.exceptions import FatalProviderError

    svc = SpeakerDetectionService()
    mock_pool = MagicMock()
    mock_pool.submit_chunk.side_effect = TimeoutError('chunk 0 exceeded 600s')

    with (
        patch('subprocess.run') as mock_run,
        patch('tempfile.NamedTemporaryFile') as mock_tmp,
        patch(
            'server.apps.rendering.speaker_detection._probe_audio_duration_s',
            return_value=100.0,
        ),
        patch(
            'server.apps.rendering.speaker_detection._get_diarization_pool',
            return_value=mock_pool,
        ),
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
        patch('pathlib.Path.unlink'),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_tmp.return_value = _patch_diarize_ffmpeg_and_tempfile()

        with pytest.raises(FatalProviderError) as exc_info:
            svc.diarize(Path('/fake.mp4'))

    assert exc_info.value.error_code == 'diarization_chunk_timeout'


def test_preload_diarization_pool_skips_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('DIARIZATION_PRELOAD', raising=False)
    assert preload_diarization_pool() is False


def test_preload_diarization_pool_starts_pool_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering import speaker_detection as sd_module

    sd_module._diarization_pool = None
    monkeypatch.setenv('DIARIZATION_PRELOAD', '1')

    with (
        patch(
            'server.apps.rendering.speaker_detection._DiarizationPool',
        ) as mock_pool_cls,
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
    ):
        assert preload_diarization_pool() is True
        assert preload_diarization_pool() is True

    mock_pool_cls.assert_called_once()


def test_preload_diarization_pool_skips_when_django_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('DIARIZATION_PRELOAD', '1')

    with patch.dict(sys.modules, {'django.conf': None}):
        assert preload_diarization_pool() is False


def test_preload_diarization_pool_skips_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('DIARIZATION_PRELOAD', '1')

    with patch('django.conf.settings.HUGGINGFACE_TOKEN', '', create=True):
        assert preload_diarization_pool() is False


def test_preload_diarization_pool_returns_false_on_pool_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.apps.rendering import speaker_detection as sd_module

    sd_module._diarization_pool = None
    monkeypatch.setenv('DIARIZATION_PRELOAD', '1')

    with (
        patch(
            'server.apps.rendering.speaker_detection._DiarizationPool',
            side_effect=RuntimeError('boom'),
        ),
        patch(
            'django.conf.settings.HUGGINGFACE_TOKEN',
            'hf-test-token',
            create=True,
        ),
    ):
        assert preload_diarization_pool() is False
