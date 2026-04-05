from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from ***REMOVED***.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_dashboard_redirects_anonymous() -> None:
    client = Client()
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_accessible_to_staff() -> None:
    user = UserFactory(is_staff=True)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 200
    assert b"ReelForge" in response.content


@pytest.mark.django_db
def test_dashboard_forbidden_to_non_staff() -> None:
    user = UserFactory(is_staff=False)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_clipping_job_list_accessible_to_staff() -> None:
    from ***REMOVED***.clipping.tests.factories import ClippingJobFactory

    user = UserFactory(is_staff=True)
    ClippingJobFactory()
    client = Client()
    client.force_login(user)
    response = client.get(reverse("clipping:job_list"))
    assert response.status_code == 200
    assert b"Clipping Jobs" in response.content


@pytest.mark.django_db
def test_clipping_job_list_filters_by_status() -> None:
    from ***REMOVED***.clipping.models import ClippingJob
    from ***REMOVED***.clipping.tests.factories import ClippingJobFactory

    user = UserFactory(is_staff=True)
    ClippingJobFactory(status=ClippingJob.Status.COMPLETED)
    ClippingJobFactory(status=ClippingJob.Status.ANALYZING)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("clipping:job_list") + "?status=COMPLETED")
    assert response.status_code == 200


@pytest.mark.django_db
def test_candidate_detail_accessible_to_staff() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory

    user = UserFactory(is_staff=True)
    candidate = ClipCandidateFactory()
    client = Client()
    client.force_login(user)
    response = client.get(
        reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk})
    )
    assert response.status_code == 200
