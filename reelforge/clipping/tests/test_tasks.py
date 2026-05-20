from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory
from ***REMOVED***.clipping.tests.factories import ClipRenderFactory
from ***REMOVED***.clipping.tests.factories import ClipStyleConfigFactory


@pytest.mark.django_db
def test_render_clip_creates_new_clip_render_when_no_render_id() -> None:
    from ***REMOVED***.clipping.models import ClipRender
    from ***REMOVED***.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    ClipStyleConfigFactory(candidate=candidate)

    with patch("***REMOVED***.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, patch(
        "***REMOVED***.clipping.tasks.get_clip_render_path"
    ) as mock_path, patch("***REMOVED***.clipping.tasks.Path") as mock_path_cls:
        mock_path.return_value = Path("/media/test.mp4")
        mock_path_cls.return_value = Path("/media/source.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline._build_stages.return_value = []
        mock_pipeline_cls.return_value = mock_pipeline

        render_clip.apply(args=[str(candidate.pk)])

    assert ClipRender.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_render_clip_uses_existing_render_when_clip_render_id_provided() -> None:
    from ***REMOVED***.clipping.models import ClipRender
    from ***REMOVED***.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    render = ClipRenderFactory(candidate=candidate)
    ClipStyleConfigFactory(candidate=candidate)

    with patch("***REMOVED***.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, patch(
        "***REMOVED***.clipping.tasks.get_clip_render_path"
    ) as mock_path:
        mock_path.return_value = Path("/media/test.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline._build_stages.return_value = []
        mock_pipeline_cls.return_value = mock_pipeline

        render_clip.apply(
            args=[str(candidate.pk)],
            kwargs={
                "clip_render_id": str(render.pk),
                "start_from_stage": 3,
            },
        )

    # Should still be the same render, not a new one
    assert ClipRender.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_analyze_clips_sets_failed_status_on_final_retry() -> None:
    """On the final retry, analyze_clips must mark the job FAILED instead of retrying again."""
    from unittest.mock import patch

    from django.core.files.base import ContentFile

    from ***REMOVED***.clipping.models import ClippingJob
    from ***REMOVED***.clipping.tasks import analyze_clips

    job = ClippingJobFactory(status=ClippingJob.Status.ANALYZING)
    # Provide a real-ish downloaded_file so the task doesn't fail on the path check
    job.downloaded_file.save("fake_video.mp4", ContentFile(b"fake"), save=True)

    # Patch all analysis helpers + service at their source modules
    with (
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_speaker_diarization",
            return_value={"segments": []},
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_scene_detection",
            return_value=[],
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_face_detection_for_speakers",
            return_value={},
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.merge_transcript_with_diarization",
            return_value={},
        ),
        patch(
            "***REMOVED***.clipping.services.ClipAnalysisService.analyze",
            side_effect=RuntimeError("analysis boom"),
        ),
        patch("***REMOVED***.clipping.sse.emit_job_event"),
    ):
        # Simulate Celery executing this as the final retry (retries == max_retries)
        analyze_clips.apply(
            args=[str(job.pk)],
            kwargs={},
            retries=analyze_clips.max_retries,
        )

    job.refresh_from_db()
    assert job.status == ClippingJob.Status.FAILED
    assert "analysis boom" in job.last_error


@pytest.mark.django_db
def test_analyze_clips_always_awaits_approval() -> None:
    """analyze_clips must always transition to AWAITING_CLIP_APPROVAL — no auto-approve."""
    from unittest.mock import patch

    from django.core.files.base import ContentFile

    from ***REMOVED***.clipping.models import ClippingJob
    from ***REMOVED***.clipping.tasks import analyze_clips
    from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory

    job = ClippingJobFactory(status=ClippingJob.Status.ANALYZING)
    job.downloaded_file.save("fake_video.mp4", ContentFile(b"fake"), save=True)
    candidates = [ClipCandidateFactory(clipping_job=job) for _ in range(2)]

    with (
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_speaker_diarization",
            return_value={"segments": []},
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_scene_detection",
            return_value=[],
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.run_face_detection_for_speakers",
            return_value={},
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.merge_transcript_with_diarization",
            return_value={},
        ),
        patch(
            "***REMOVED***.clipping.services.ClipAnalysisService.analyze",
            return_value=candidates,
        ),
        patch(
            "***REMOVED***.clipping.analysis_helpers.build_analysis_manifest",
            return_value={"candidates": 2},
        ),
        patch("***REMOVED***.clipping.sse.emit_job_event"),
    ):
        analyze_clips.apply(args=[str(job.pk)])

    job.refresh_from_db()
    assert job.status == ClippingJob.Status.AWAITING_CLIP_APPROVAL


# ── Manual Clip Bypass ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_transcribe_video_bypass_skips_analyze_and_creates_manual_candidate() -> None:
    from decimal import Decimal
    from unittest.mock import MagicMock, patch

    from django.core.files.base import ContentFile

    from ***REMOVED***.clipping.models import ClipCandidate, ClippingJob
    from ***REMOVED***.clipping.tasks import transcribe_video

    job = ClippingJobFactory(
        status=ClippingJob.Status.TRANSCRIBING,
        skip_analysis=True,
        source_duration_sec=600.0,
        source_title="My Pre-edited Video",
    )
    job.downloaded_file.save("video.mp4", ContentFile(b"fake"), save=True)
    mock_result = MagicMock()
    mock_result.transcript_text = "hello world"
    mock_result.transcript_json = {"segments": []}
    mock_result.cost_usd = Decimal("0.01")
    mock_result.provider = "whisper"

    with (
        patch("***REMOVED***.clipping.tasks.ffmpeg") as mock_ffmpeg,
        patch("***REMOVED***.services.transcription.whisper.WhisperTranscriptionService") as mock_ws_cls,
        patch("***REMOVED***.clipping.tasks.analyze_clips") as mock_analyze,
        patch("***REMOVED***.clipping.sse.emit_job_event"),
        patch("tempfile.NamedTemporaryFile"),
    ):
        mock_ffmpeg.input.return_value.output.return_value.overwrite_output.return_value.run.return_value = None
        mock_ws_cls.return_value.transcribe.return_value = mock_result
        transcribe_video.apply(args=[str(job.pk)])

    mock_analyze.delay.assert_not_called()
    job.refresh_from_db()
    assert job.status == ClippingJob.Status.AWAITING_CLIP_APPROVAL
    candidates = ClipCandidate.objects.filter(clipping_job=job)
    assert candidates.count() == 1
    candidate = candidates.first()
    assert candidate.is_manual is True
    assert candidate.start_sec == 0.0
    assert candidate.end_sec == 600.0
    assert candidate.title == "My Pre-edited Video"


@pytest.mark.django_db
def test_transcribe_video_normal_path_dispatches_analyze_clips() -> None:
    from decimal import Decimal
    from unittest.mock import MagicMock, patch

    from django.core.files.base import ContentFile

    from ***REMOVED***.clipping.models import ClipCandidate, ClippingJob
    from ***REMOVED***.clipping.tasks import transcribe_video

    job = ClippingJobFactory(
        status=ClippingJob.Status.TRANSCRIBING,
        skip_analysis=False,
        source_duration_sec=600.0,
    )
    job.downloaded_file.save("video.mp4", ContentFile(b"fake"), save=True)
    mock_result = MagicMock()
    mock_result.transcript_text = "hello"
    mock_result.transcript_json = {"segments": []}
    mock_result.cost_usd = Decimal("0.005")
    mock_result.provider = "whisper"

    with (
        patch("***REMOVED***.clipping.tasks.ffmpeg") as mock_ffmpeg,
        patch("***REMOVED***.services.transcription.whisper.WhisperTranscriptionService") as mock_ws_cls,
        patch("***REMOVED***.clipping.tasks.analyze_clips") as mock_analyze,
        patch("***REMOVED***.clipping.sse.emit_job_event"),
        patch("tempfile.NamedTemporaryFile"),
    ):
        mock_ffmpeg.input.return_value.output.return_value.overwrite_output.return_value.run.return_value = None
        mock_ws_cls.return_value.transcribe.return_value = mock_result
        transcribe_video.apply(args=[str(job.pk)])

    mock_analyze.delay.assert_called_once_with(str(job.pk))
    assert ClipCandidate.objects.filter(clipping_job=job, is_manual=True).count() == 0


@pytest.mark.django_db
def test_create_manual_candidate_probes_duration_for_upload_jobs() -> None:
    from unittest.mock import patch

    from django.core.files.base import ContentFile

    from ***REMOVED***.clipping.models import ClippingJob
    from ***REMOVED***.clipping.tasks import _create_manual_candidate

    job = ClippingJobFactory(
        source_type=ClippingJob.SourceType.UPLOAD,
        source_duration_sec=None,
        source_title="Uploaded Video",
    )
    job.downloaded_file.save("upload.mp4", ContentFile(b"fake"), save=True)
    with patch("***REMOVED***.clipping.tasks.ffmpeg") as mock_ffmpeg:
        mock_ffmpeg.probe.return_value = {"format": {"duration": "300.5"}}
        candidate = _create_manual_candidate(job)

    assert candidate.end_sec == 300.5
    assert candidate.is_manual is True
    job.refresh_from_db()
    assert job.source_duration_sec == 300.5
