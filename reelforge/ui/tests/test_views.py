from __future__ import annotations

import http

import pytest
from django.test import Client
from django.urls import reverse

from ***REMOVED***.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_dashboard_redirects_anonymous() -> None:
    client = Client()
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == http.HTTPStatus.FOUND
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_accessible_to_staff() -> None:
    user = UserFactory(is_staff=True)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == http.HTTPStatus.OK
    assert b"ReelForge" in response.content


@pytest.mark.django_db
def test_dashboard_forbidden_to_non_staff() -> None:
    user = UserFactory(is_staff=False)
    client = Client()
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == http.HTTPStatus.FOUND
