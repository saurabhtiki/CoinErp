"""Core Step 11, Part D: the health page checks the database and says clearly when it is down."""
import pytest
from django.db import DatabaseError
from django.urls import reverse


@pytest.mark.django_db
def test_health_is_ok_when_database_works(client):
    response = client.get(reverse("core:healthz"))
    assert response.status_code == 200 and response.content == b"ok"


@pytest.mark.django_db
def test_health_says_503_with_clear_message_when_database_is_down(client, monkeypatch, caplog):
    def broken_cursor(*args, **kwargs):
        raise DatabaseError("connection refused")

    monkeypatch.setattr("core.views.connection.cursor", broken_cursor)
    response = client.get(reverse("core:healthz"))

    assert response.status_code == 503
    assert b"Database is not reachable" in response.content
    assert "Health check failed" in caplog.text  # the error is logged


def test_production_accepts_the_local_health_check_host():
    import subprocess
    import sys

    from tests.test_https import PROD_ENV

    import os
    env = {**os.environ, **PROD_ENV}
    code = "import django;django.setup();from django.conf import settings;print('127.0.0.1' in settings.ALLOWED_HOSTS)"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.stdout.strip() == "True", result.stderr


def test_deploy_script_has_valid_shell_syntax():
    import shutil
    import subprocess

    sh = shutil.which("sh") or shutil.which("bash")
    if not sh:
        pytest.skip("no shell available")
    result = subprocess.run([sh, "-n", "docker/deploy.sh"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
