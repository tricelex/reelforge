from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_redirects_anonymous(client):
    response = client.get("/app/")
    assert response.status_code == 302
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_dashboard_returns_200_for_staff(client, django_user_model):
    django_user_model.objects.create_superuser(
        email="staff@test.com",
        password="testpass123",
    )
    client.login(email="staff@test.com", password="testpass123")
    response = client.get("/app/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_active_jobs_partial_requires_staff(client):
    response = client.get("/app/partials/active-jobs/")
    assert response.status_code == 302  # redirects to login


@pytest.mark.django_db
def test_dashboard_active_jobs_partial_returns_200(client, django_user_model):
    django_user_model.objects.create_superuser(
        email="staff2@test.com",
        password="testpass123",
    )
    client.login(email="staff2@test.com", password="testpass123")
    response = client.get("/app/partials/active-jobs/")
    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
