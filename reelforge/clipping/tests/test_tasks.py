from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClipRenderFactory
from ***REMOVED***.clipping.tests.factories import ClipStyleConfigFactory
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory


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
    from ***REMOVED***.clipping.tests.factories import ClippingJobFactory

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
    from ***REMOVED***.clipping.tests.factories import ClippingJobFactory

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
