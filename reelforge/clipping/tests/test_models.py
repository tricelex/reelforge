from __future__ import annotations

import pytest
from django_fsm import TransitionNotAllowed

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClippingJob

from .factories import ClipCandidateFactory
from .factories import ClippingJobFactory


@pytest.mark.django_db
def test_clipping_job_initial_status() -> None:
    job = ClippingJobFactory()
    assert job.status == ClippingJob.Status.INITIALIZING


@pytest.mark.django_db
def test_clipping_job_begin_download_transition() -> None:
    job = ClippingJobFactory()
    job.begin_download()
    job.save(update_fields=["status", "updated_at"])
    job.refresh_from_db()
    assert job.status == ClippingJob.Status.DOWNLOADING


@pytest.mark.django_db
def test_clipping_job_cannot_skip_states() -> None:
    job = ClippingJobFactory()
    with pytest.raises(TransitionNotAllowed):
        job.begin_transcription()


@pytest.mark.django_db
def test_clipping_job_mark_failed_from_any_state() -> None:
    job = ClippingJobFactory()
    job.begin_download()
    job.save(update_fields=["status", "updated_at"])
    job.mark_failed(error="Test error")
    job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
    assert job.status == ClippingJob.Status.FAILED
    assert job.last_error == "Test error"


@pytest.mark.django_db
def test_clip_candidate_duration_too_short_raises() -> None:
    job = ClippingJobFactory()
    candidate = ClipCandidate(
        clipping_job=job,
        start_sec=0.0,
        end_sec=20.0,
        title="Short clip",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="30"):
        candidate.full_clean()


@pytest.mark.django_db
def test_clip_candidate_duration_too_long_raises() -> None:
    job = ClippingJobFactory()
    candidate = ClipCandidate(
        clipping_job=job,
        start_sec=0.0,
        end_sec=200.0,
        title="Long clip",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="180"):
        candidate.full_clean()


@pytest.mark.django_db
def test_clip_candidate_overlap_detection() -> None:
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, start_sec=0.0, end_sec=60.0)
    overlapping = ClipCandidate(
        clipping_job=job,
        start_sec=30.0,
        end_sec=90.0,
        title="Overlapping",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    with pytest.raises(Exception, match="overlaps"):
        overlapping.full_clean()


@pytest.mark.django_db
def test_clip_candidate_no_overlap_different_jobs() -> None:
    job1 = ClippingJobFactory()
    job2 = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job1, start_sec=0.0, end_sec=60.0)
    # Same timestamps but different job — should NOT raise
    candidate = ClipCandidate(
        clipping_job=job2,
        start_sec=0.0,
        end_sec=60.0,
        title="No overlap",
        hook_text="hook",
        relevance_score=5.0,
        reason="test",
    )
    candidate.full_clean()  # Should not raise


@pytest.mark.django_db
def test_clip_candidate_duration_property() -> None:
    candidate = ClipCandidateFactory(start_sec=30.0, end_sec=90.0)
    assert candidate.duration_sec == 60.0


@pytest.mark.django_db
def test_clip_layout_config_default_render_mode() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig.objects.create(candidate=candidate)
    assert config.render_mode == "SMART_CROP"


@pytest.mark.django_db
def test_has_manual_smart_crop_true_when_all_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is True


@pytest.mark.django_db
def test_has_manual_smart_crop_false_when_any_field_null() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=None,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is False


@pytest.mark.django_db
def test_has_spatial_regions_true_when_all_ab_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
    )
    assert config.has_spatial_regions is True


@pytest.mark.django_db
def test_has_spatial_regions_false_when_region_b_missing() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
    )
    assert config.has_spatial_regions is False


@pytest.mark.django_db
def test_clip_layout_config_str() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig.objects.create(candidate=candidate)
    assert "Smart Crop" in str(config)
