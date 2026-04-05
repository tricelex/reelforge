from __future__ import annotations

import pytest
from django.urls import reverse

from ***REMOVED***.channels.choices import NicheCategory
from ***REMOVED***.channels.models import Channel
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClippingJob


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


@pytest.mark.django_db
def test_job_status_partial_sets_terminal_for_completed_job(
    staff_client, clipping_job
):
    clipping_job.status = ClippingJob.Status.COMPLETED
    clipping_job.save(update_fields=["status", "updated_at"])
    response = staff_client.get(f"/app/clipping/{clipping_job.id}/status/")
    assert response.status_code == 200
    assert b'data-terminal="true"' in response.content
