from __future__ import annotations

import pytest
from django.urls import reverse

from reelforge.channels.choices import NicheCategory
from reelforge.channels.models import Channel
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob


@pytest.fixture
def staff_client(client, django_user_model):
    django_user_model.objects.create_superuser(
        email="staff@test.com",
        password="testpass123",
    )
    client.login(email="staff@test.com", password="testpass123")
    return client


@pytest.fixture
def channel(db):
    return Channel.objects.create(
        name="Test Channel",
        slug="test-channel",
        niche_category=NicheCategory.TECH,
    )


@pytest.fixture
def clipping_job(db, channel):
    return ClippingJob.objects.create(
        channel=channel,
        source_url="https://youtube.com/watch?v=test",
        source_title="Test Video",
        clips_requested=5,
    )


@pytest.mark.django_db
def test_job_list_requires_staff(client):
    response = client.get("/app/clipping/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_job_list_returns_200(staff_client):
    response = staff_client.get("/app/clipping/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_job_list_shows_jobs(staff_client, clipping_job):
    response = staff_client.get("/app/clipping/")
    assert response.status_code == 200
    assert b"Test Video" in response.content


@pytest.mark.django_db
def test_job_list_filter_by_status(staff_client, clipping_job):
    response = staff_client.get("/app/clipping/?status=AWAITING_CLIP_APPROVAL")
    assert response.status_code == 200
    # clipping_job is INITIALIZING so should not appear
    assert b"Test Video" not in response.content


@pytest.mark.django_db
def test_job_detail_returns_200(staff_client, clipping_job):
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/")
    assert response.status_code == 200
    assert b"Test Video" in response.content


@pytest.mark.django_db
def test_job_status_partial_returns_200(staff_client, clipping_job):
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/status/")
    assert response.status_code == 200


@pytest.fixture
def candidate(db, clipping_job):
    return ClipCandidate.objects.create(
        clipping_job=clipping_job,
        start_sec=60.0,
        end_sec=120.0,
        title="Test Clip",
        relevance_score=8.5,
    )


@pytest.mark.django_db
def test_approve_candidate(staff_client, candidate):
    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/approve/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is True
    assert candidate.status == ClipCandidate.CandidateStatus.APPROVED


@pytest.mark.django_db
def test_reject_candidate(staff_client, candidate):
    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/reject/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is False
    assert candidate.status == ClipCandidate.CandidateStatus.REJECTED


@pytest.mark.django_db
def test_undo_reject_candidate(staff_client, candidate):
    # Reject first (no FSM on ClipCandidate.status - it's a plain CharField)
    ClipCandidate.objects.filter(pk=candidate.pk).update(
        approved=False,
        status=ClipCandidate.CandidateStatus.REJECTED,
    )
    response = staff_client.post(f"/app/clipping/clips/{candidate.id}/undo-reject/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is None
    assert candidate.status == ClipCandidate.CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_approve_all_candidates(staff_client, clipping_job, candidate):
    response = staff_client.post(f"/app/clipping/{clipping_job.id}/approve-all/")
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.approved is True


@pytest.mark.django_db
def test_job_status_partial_sets_terminal_for_completed_job(
    staff_client, clipping_job
):
    # Use update() to bypass FSMField protected assignment in tests
    ClippingJob.objects.filter(pk=clipping_job.pk).update(
        status=ClippingJob.Status.COMPLETED
    )
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/status/")
    assert response.status_code == 200
    assert b'data-terminal="true"' in response.content
