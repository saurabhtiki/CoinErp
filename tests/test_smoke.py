import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_home_redirects_anonymous_user_to_login(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.django_db
def test_home_opens_for_logged_in_user(client):
    user = get_user_model().objects.create_user(email="ravi@example.com", password="a-long-password-123")
    client.force_login(user)

    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert b"Group ERP" in response.content


@pytest.mark.django_db
def test_health_check_needs_no_login(client):
    response = client.get(reverse("core:healthz"))

    assert response.status_code == 200
    assert response.content == b"ok"
