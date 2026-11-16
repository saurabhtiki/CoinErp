"""Core Step 11, Part C: production settings pass `check --deploy`; http is sent to https; 2FA pages work on https."""
import os
import subprocess
import sys

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()
PROD_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "SECRET_KEY": "k7#Pq9!zXw2Lm5$Vt8&Rb3Nc6Hd0Gf4Jy1Sa%Ue^Ki-Oo_Tz+Ew~Qn=Ml",
    "ALLOWED_HOSTS": "erp.example.com",
    "DATABASE_URL": "sqlite:///:memory:",
}


def run_deploy_check(**changes):
    env = {**os.environ, **PROD_ENV, **changes}
    return subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def test_production_settings_pass_the_deploy_check():
    result = run_deploy_check()
    assert result.returncode == 0, result.stdout + result.stderr


def test_deploy_check_fails_when_https_redirect_is_off():
    """Proves the check above really looks at our settings."""
    result = run_deploy_check(SECURE_SSL_REDIRECT="False")
    assert result.returncode != 0
    assert "SECURE_SSL_REDIRECT" in result.stdout + result.stderr


@pytest.fixture
def https_on(settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.ALLOWED_HOSTS = ["testserver"]


@pytest.mark.django_db
def test_plain_http_is_sent_to_https(client, https_on):
    response = client.get("/accounts/login/")
    assert response.status_code == 301 and response["Location"].startswith("https://")


@pytest.mark.django_db
def test_login_page_works_when_caddy_says_https(client, https_on):
    response = client.get("/accounts/login/", HTTP_X_FORWARDED_PROTO="https")
    assert response.status_code == 200


@pytest.mark.django_db
def test_health_check_works_over_plain_http(client, https_on):
    assert client.get("/healthz/").status_code == 200


@pytest.mark.django_db
def test_2fa_pages_work_behind_https(client, https_on):
    """A superuser must set up 2FA: the redirect and the setup page work through the proxy header."""
    user = User.objects.create_user(email="boss@example.com", password="a-long-password-123", first_name="Boss",
                                    is_superuser=True)
    client.force_login(user)

    redirect = client.get("/", HTTP_X_FORWARDED_PROTO="https")
    assert redirect.status_code == 302 and "/2fa/setup/" in redirect["Location"]

    page = client.get(redirect["Location"], HTTP_X_FORWARDED_PROTO="https")
    assert page.status_code == 200
    assert client.cookies["sessionid"]["secure"]
