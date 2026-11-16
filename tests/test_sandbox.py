"""Core Step 11, Part A: sandbox bar, no real email, Sent mail page, demo data, reset_sandbox."""
import importlib

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory

from apps.tasks.models import RecurringTask, Task
from config.demo_data import DEMO_COMPANY_CODE, DemoDataExists, demo_password, load_demo_data
from core.masters.models import Company
from core.notifications import services as notification_services

User = get_user_model()


@pytest.fixture
def sandbox(settings):
    settings.ENVIRONMENT = "sandbox"
    settings.IS_SANDBOX = True


@pytest.fixture(autouse=True)
def no_2fa_prompt(monkeypatch):
    """Superusers must pass 2FA before any page; these tests are about the sandbox, not 2FA."""
    monkeypatch.setattr("core.accounts.middleware.roles_require_2fa", lambda user: False)


@pytest.fixture(autouse=True)
def private_folder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def make_staff(email, superuser=False):
    return User.objects.create_user(email=email, password="a-long-password-123", first_name="Pat", is_superuser=superuser)


# --- Banner -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_banner_shows_only_in_sandbox(client, settings):
    user = make_staff("pat@example.com", superuser=True)
    client.force_login(user)
    assert b"SANDBOX: test data only" not in client.get("/").content

    settings.IS_SANDBOX = True
    assert b"SANDBOX: test data only" in client.get("/").content


@pytest.mark.django_db
def test_banner_shows_on_login_page_in_sandbox(client, sandbox):
    assert b"SANDBOX: test data only" in client.get("/accounts/login/").content


def test_sandbox_environment_never_uses_the_smtp_backend(monkeypatch):
    from config.settings import base

    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
    try:
        reloaded = importlib.reload(base)
        assert reloaded.IS_SANDBOX
        assert reloaded.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"
    finally:
        monkeypatch.undo()
        importlib.reload(base)


# --- Sent mail page -----------------------------------------------------------------------


@pytest.mark.django_db
def test_sent_mail_page_does_not_exist_on_production(client, settings):
    settings.ENVIRONMENT = "production"
    client.force_login(make_staff("pat@example.com", superuser=True))
    assert client.get("/notifications/sent-mail/").status_code == 404


@pytest.mark.django_db
def test_sent_mail_lists_own_mail_and_superuser_sees_all(client, sandbox):
    pat = make_staff("pat@example.com")
    sam = make_staff("sam@example.com")
    boss = make_staff("boss@example.com", superuser=True)
    notification_services.notify(pat, "Hello Pat", "for pat only")
    notification_services.notify(sam, "Hello Sam", "for sam only")

    client.force_login(pat)
    own = client.get("/notifications/sent-mail/").content.decode()
    assert "Hello Pat" in own
    assert "Hello Sam" not in own

    client.force_login(boss)
    everything = client.get("/notifications/sent-mail/").content.decode()
    assert "Hello Pat" in everything and "Hello Sam" in everything


@pytest.mark.django_db
def test_sent_mail_needs_login(client, sandbox):
    assert client.get("/notifications/sent-mail/").status_code == 302


# --- Demo data ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_demo_data_creates_companies_people_tasks_and_a_rule():
    people = load_demo_data()

    assert Company.objects.filter(code=DEMO_COMPANY_CODE).exists()
    assert Task.objects.count() >= 5
    assert RecurringTask.objects.filter(title="GSTR1").exists()
    assert all(person.email.endswith("@demo.test") for person in people.values())
    request = RequestFactory().post("/")
    assert authenticate(request, username="manager@demo.test", password=demo_password()) is not None


@pytest.mark.django_db
def test_demo_data_cannot_be_loaded_twice():
    load_demo_data()
    with pytest.raises(DemoDataExists):
        load_demo_data()


@pytest.mark.django_db
def test_load_demo_data_command_refuses_on_production(settings):
    settings.ENVIRONMENT = "production"
    with pytest.raises(CommandError, match="production"):
        call_command("load_demo_data")
    assert not Company.objects.exists()


# --- reset_sandbox ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reset_sandbox_refuses_when_not_sandbox(settings):
    settings.ENVIRONMENT = "production"
    settings.IS_SANDBOX = False
    Company.objects.create(name="Real Co", code="REAL")

    with pytest.raises(CommandError, match="only on the sandbox"):
        call_command("reset_sandbox", yes=True)
    assert Company.objects.filter(code="REAL").exists()


@pytest.mark.django_db(transaction=True)
def test_reset_sandbox_needs_confirmation(sandbox):
    Company.objects.create(name="Old Co", code="OLD")
    with pytest.raises(CommandError, match="--yes"):
        call_command("reset_sandbox")
    assert Company.objects.filter(code="OLD").exists()


@pytest.mark.django_db(transaction=True)
def test_reset_sandbox_wipes_old_data_and_files_then_loads_demo_data(sandbox, tmp_path):
    Company.objects.create(name="Old Co", code="OLD")
    (tmp_path / "old-upload.pdf").write_bytes(b"%PDF-1.4 old")

    call_command("reset_sandbox", yes=True)

    assert not Company.objects.filter(code="OLD").exists()
    assert Company.objects.filter(code=DEMO_COMPANY_CODE).exists()
    assert not (tmp_path / "old-upload.pdf").exists()
