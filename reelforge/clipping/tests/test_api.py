from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.tests.factories import (
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
from ***REMOVED***.users.tests.factories import UserFactory


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


# ── Auth — logout ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_logout_blacklists_refresh_token(staff_user):
    client = APIClient()
    # Obtain tokens
    response = client.post(
        "/api/v1/auth/token/",
        {"email": staff_user.email, "password": "password"},
        format="json",
    )
    assert response.status_code == 200
    refresh_token = response.json()["refresh"]

    # Logout — blacklist the refresh token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    logout_response = client.post(
        "/api/v1/auth/logout/",
        {"refresh": refresh_token},
        format="json",
    )
    assert logout_response.status_code == 200

    # Attempt to refresh using the blacklisted token — should fail
    refresh_response = client.post(
        "/api/v1/auth/token/refresh/",
        {"refresh": refresh_token},
        format="json",
    )
    assert refresh_response.status_code == 401


# ── Auth — /me/ ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_me_returns_current_user(auth_client, staff_user):
    response = auth_client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == staff_user.email
    assert data["is_staff"] is True
    assert "name" in data
    assert "id" in data
    assert "date_joined" in data
    # oauth_credentials must never be exposed
    assert "oauth_credentials" not in data
    assert "password" not in data


@pytest.mark.django_db
def test_me_requires_authentication():
    client = APIClient()
    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 401

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
    with patch("***REMOVED***.clipping.views.jobs.download_source_video.delay") as mock_delay:
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
    with patch("***REMOVED***.clipping.views.renders.render_clip.delay") as mock_delay:
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


# ── Social Accounts ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_social_accounts_returns_paginated(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory.create_batch(3, is_active=True)
    response = auth_client.get("/api/v1/social-accounts/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 3
    result = data["results"][0]
    # Check expected fields are present
    assert "id" in result
    assert "platform" in result
    assert "platform_display" in result
    assert "handle" in result
    assert "display_name" in result
    assert "is_active" in result
    assert "channel_id" in result
    assert "channel_name" in result
    # Sensitive fields must never appear
    assert "oauth_credentials" not in result


@pytest.mark.django_db
def test_filter_social_accounts_by_platform(auth_client):
    from ***REMOVED***.channels.models import SocialAccount
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory(platform=SocialAccount.Platform.TIKTOK)
    SocialAccountFactory(platform=SocialAccount.Platform.INSTAGRAM)
    response = auth_client.get("/api/v1/social-accounts/?platform=TIKTOK")
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(r["platform"] == "TIKTOK" for r in results)


@pytest.mark.django_db
def test_filter_social_accounts_by_is_active(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    SocialAccountFactory(is_active=True)
    SocialAccountFactory(is_active=False)
    response = auth_client.get("/api/v1/social-accounts/?is_active=true")
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(r["is_active"] is True for r in results)


@pytest.mark.django_db
def test_retrieve_social_account(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    account = SocialAccountFactory()
    response = auth_client.get(f"/api/v1/social-accounts/{account.id}/")
    assert response.status_code == 200
    assert response.json()["id"] == str(account.id)


@pytest.mark.django_db
def test_social_accounts_read_only(auth_client):
    from ***REMOVED***.channels.tests.factories import SocialAccountFactory

    account = SocialAccountFactory()
    # POST to list — should be 405 Method Not Allowed
    response = auth_client.post("/api/v1/social-accounts/", {}, format="json")
    assert response.status_code == 405
    # DELETE — should be 405
    response = auth_client.delete(f"/api/v1/social-accounts/{account.id}/")
    assert response.status_code == 405

# ── ClipCandidate list ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_candidates_by_job(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job)
    ClipCandidateFactory(clipping_job=job)
    # Candidate from a different job — should not appear
    ClipCandidateFactory()
    response = auth_client.get(f"/api/v1/clipping/candidates/?job={job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["results"]) == 2

