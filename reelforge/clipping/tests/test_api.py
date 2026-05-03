from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from reelforge.channels.tests.factories import SocialAccountFactory
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipRender
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.tests.factories import (
    ClipCandidateFactory,
    ClipLayoutConfigFactory,
    ClipMediaAssetFactory,
    ClipMusicAssetFactory,
    ClipRenderFactory,
    ClipRenderTemplateFactory,
    ClippingJobFactory,
    ClipStyleConfigFactory,
    ClipTimedOverlayFactory,
)
from reelforge.users.tests.factories import UserFactory


@pytest.fixture
def staff_user(db):
    return UserFactory(is_staff=True, is_superuser=True, password="password")


@pytest.fixture
def auth_client(db, staff_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": staff_user.email, "password": "password"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    return client


# ── JWT ───────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_jwt_obtain_token(staff_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": staff_user.email, "password": "password"},
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.json()
    assert "refresh" in response.json()


@pytest.mark.django_db
def test_unauthenticated_request_returns_401():
    client = APIClient()
    response = client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_non_staff_user_returns_403(db):
    user = UserFactory(is_staff=False, password="password")
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "password"},
        format="json",
    )
    token = response.json().get("access")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 403


# ── ClippingJob ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_clipping_jobs(auth_client):
    ClippingJobFactory.create_batch(3)
    response = auth_client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["results"]) == 3


@pytest.mark.django_db
def test_create_clipping_job_dispatches_download(auth_client):
    with patch("reelforge.clipping.views.jobs.download_source_video.delay") as mock_delay:
        account = SocialAccountFactory()
        response = auth_client.post(
            "/api/v1/clipping/jobs/",
            {
                "social_account": str(account.id),
                "source_type": "YOUTUBE_URL",
                "source_url": "https://youtube.com/watch?v=test",
                "clips_requested": 3,
            },
            format="json",
        )
        assert response.status_code == 201
        mock_delay.assert_called_once()


@pytest.mark.django_db
def test_retrieve_job_includes_candidates(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job)
    ClipCandidateFactory(clipping_job=job)
    response = auth_client.get(f"/api/v1/clipping/jobs/{job.id}/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["candidates"]) == 2


@pytest.mark.django_db
def test_start_render_requires_approved_candidate(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/jobs/{job.id}/start-render/")
    assert response.status_code == 400
    assert "No approved candidates" in response.json()["detail"]


@pytest.mark.django_db
def test_approve_all_approves_proposed_candidates(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/jobs/{job.id}/approve-all/")
    assert response.status_code == 200
    assert response.json()["approved_count"] == 2


# ── ClipCandidate ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_approve_candidate(auth_client):
    candidate = ClipCandidateFactory(status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/candidates/{candidate.id}/approve/")
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["approved"] is True


@pytest.mark.django_db
def test_reject_candidate(auth_client):
    candidate = ClipCandidateFactory(status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(
        f"/api/v1/clipping/candidates/{candidate.id}/reject/",
        {"reason": "Not relevant"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


@pytest.mark.django_db
def test_undo_reject_resets_to_proposed(auth_client):
    candidate = ClipCandidateFactory(
        status=ClipCandidate.CandidateStatus.REJECTED,
        approved=False,
        rejection_reason="Not relevant",
    )
    response = auth_client.post(f"/api/v1/clipping/candidates/{candidate.id}/undo-reject/")
    assert response.status_code == 200
    assert response.json()["status"] == "PROPOSED"


@pytest.mark.django_db
def test_retrieve_candidate_returns_correct_job(auth_client):
    job1 = ClippingJobFactory()
    job2 = ClippingJobFactory()
    c1 = ClipCandidateFactory(clipping_job=job1)
    ClipCandidateFactory(clipping_job=job2)
    # Candidates endpoint only supports retrieve (no list action)
    response = auth_client.get(f"/api/v1/clipping/candidates/{c1.id}/")
    assert response.status_code == 200
    assert response.json()["clipping_job"] == str(job1.id)


# ── ClipLayoutConfig ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_patch_layout_config(auth_client):
    candidate = ClipCandidateFactory()
    lc = candidate.layout_config
    response = auth_client.patch(
        f"/api/v1/clipping/layout-configs/{lc.id}/",
        {"render_mode": "CENTER_CROP"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["render_mode"] == "CENTER_CROP"


@pytest.mark.django_db
def test_reset_crop_clears_manual_fields(auth_client):
    candidate = ClipCandidateFactory()
    lc = candidate.layout_config
    lc.manual_crop_x = 100
    lc.manual_crop_y = 0
    lc.manual_crop_w = 500
    lc.manual_crop_h = 900
    lc.save()
    response = auth_client.post(f"/api/v1/clipping/layout-configs/{lc.id}/reset-crop/")
    assert response.status_code == 200
    data = response.json()
    assert data["manual_crop_x"] is None
    assert data["manual_crop_w"] is None


# ── ClipRenderTemplate ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_cannot_delete_default_template(auth_client):
    template = ClipRenderTemplateFactory(is_default=True)
    response = auth_client.delete(f"/api/v1/clipping/render-templates/{template.id}/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_set_default_marks_template_as_default(auth_client):
    t1 = ClipRenderTemplateFactory(is_default=True)
    t2 = ClipRenderTemplateFactory(is_default=False)
    response = auth_client.post(f"/api/v1/clipping/render-templates/{t2.id}/set-default/")
    assert response.status_code == 200
    t1.refresh_from_db()
    t2.refresh_from_db()
    assert t2.is_default is True
    assert t1.is_default is False


# ── ClipRender ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_resume_non_paused_render_returns_400(auth_client):
    render = ClipRenderFactory(status=ClipRender.RenderStatus.COMPLETED)
    response = auth_client.post(f"/api/v1/clipping/renders/{render.id}/resume/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_resume_paused_render_dispatches_task(auth_client):
    with patch("reelforge.clipping.views.renders.render_clip.delay") as mock_delay:
        render = ClipRenderFactory(
            status=ClipRender.RenderStatus.PAUSED_AT_GATE,
            paused_at_stage=3,
        )
        response = auth_client.post(f"/api/v1/clipping/renders/{render.id}/resume/")
        assert response.status_code == 200
        mock_delay.assert_called_once_with(
            str(render.candidate_id),
            start_from_stage=4,
            clip_render_id=str(render.id),
        )
