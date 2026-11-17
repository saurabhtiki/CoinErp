"""Email settings in Admin: one row, superuser only, scrambled password, test button, plain errors."""
import logging
import smtplib
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from core.notifications import services
from core.notifications.backends import EmailBackend
from core.notifications.models import EmailSettings, Notification, NotificationLog
from core.notifications.services import notify
from tests.test_accounts import PASSWORD, verified_admin

User = get_user_model()
SCREEN_BACKEND = "core.notifications.backends.EmailBackend"
SECRET = "abcd efgh ijkl mnop"
ADD_URL = "/admin/notifications/emailsettings/add/"
FORM = {
    "sending_on": "on", "host": "smtp.gmail.com", "port": "587", "security": "tls",
    "username": "coin@example.com", "password": SECRET, "from_name": "Coin",
    "from_address": "coin@example.com", "reply_to": "office@example.com",
}


def saved_row(**extra):
    values = {"host": "smtp.gmail.com", "port": 587, "username": "coin@example.com",
              "from_name": "Coin", "from_address": "coin@example.com",
              "password_encrypted": services.encrypt_password(SECRET), **extra}
    return EmailSettings.objects.create(**values)


def change_url(row):
    return f"/admin/notifications/emailsettings/{row.pk}/change/"


@pytest.fixture
def ravi(db):
    return User.objects.create_user(email="ravi@example.com", password=PASSWORD)


# --- E1: table, scrambled password, screen, history -------------------------------------------------------

@pytest.mark.django_db
def test_admin_saves_settings_password_is_scrambled_and_never_shown_or_in_history(client):
    verified_admin(client)

    client.post(ADD_URL, FORM)
    row = EmailSettings.objects.get()
    page = client.get(change_url(row)).content.decode()
    history = client.get(f"/admin/notifications/emailsettings/{row.pk}/history/").content.decode()

    assert row.host == "smtp.gmail.com" and row.reply_to == "office@example.com"
    assert SECRET not in row.password_encrypted and services.read_password(row) == SECRET
    assert SECRET not in page and row.password_encrypted not in page and "●●●● saved" in page
    assert SECRET not in history and row.password_encrypted not in history
    assert not hasattr(row.history.first(), "password_encrypted")  # History never stores it
    assert len(mail.outbox) == 0  # saving never sends a test


@pytest.mark.django_db
def test_blank_password_keeps_the_saved_one_and_only_one_row_exists(client):
    verified_admin(client)
    client.post(ADD_URL, FORM)
    row = EmailSettings.objects.get()

    client.post(change_url(row), {**FORM, "password": "", "host": "smtp.office365.com"})
    row.refresh_from_db()

    assert row.host == "smtp.office365.com" and services.read_password(row) == SECRET
    assert client.get(ADD_URL).status_code == 403  # no second row
    assert client.get("/admin/notifications/emailsettings/").url == change_url(row)


@pytest.mark.django_db
def test_only_the_superuser_sees_the_email_settings(client):
    row = saved_row()
    staff = User.objects.create_user(email="hr@example.com", password=PASSWORD, is_staff=True)
    client.force_login(staff)

    assert client.get(change_url(row)).status_code in (302, 403)
    assert client.post(f"/admin/notifications/emailsettings/{row.pk}/send-test/").status_code in (302, 403)
    assert "Email settings" not in client.get("/admin/").content.decode()


@pytest.mark.django_db
def test_lost_key_shows_a_red_note_asking_for_the_password_again(client, settings):
    verified_admin(client)
    row = saved_row()
    settings.EMAIL_SETTINGS_KEY = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="  # a different, valid key

    page = client.get(change_url(row)).content.decode()

    assert "Password can&#x27;t be read, please type it again" in page


@pytest.mark.django_db
def test_missing_key_refuses_to_save_a_password_in_plain_words(client, settings):
    verified_admin(client)
    settings.EMAIL_SETTINGS_KEY = ""

    page = client.post(ADD_URL, FORM).content.decode()

    assert not EmailSettings.objects.exists()
    assert "EMAIL_SETTINGS_KEY is missing in .env" in page


# --- E2: sending with the screen's settings ----------------------------------------------------------------

@pytest.mark.django_db
def test_backend_uses_the_screen_settings_and_sender(settings):
    settings.EMAIL_HOST = "smtp.from-env.com"
    saved_row(security="ssl", port=465, reply_to="office@example.com")

    backend = EmailBackend()
    message = mail.EmailMessage("Hi", "Body", None, ["ravi@example.com"])
    with mock.patch("smtplib.SMTP_SSL") as smtp:
        backend.send_messages([message])

    assert (backend.host, backend.port, backend.username, backend.password) == (
        "smtp.gmail.com", 465, "coin@example.com", SECRET)
    assert backend.use_ssl and not backend.use_tls
    assert smtp.called
    assert message.from_email == "Coin <coin@example.com>" and message.reply_to == ["office@example.com"]


@pytest.mark.django_db
def test_backend_falls_back_to_env_until_the_screen_is_saved(settings):
    settings.EMAIL_HOST, settings.EMAIL_HOST_USER = "smtp.from-env.com", "env@example.com"

    backend = EmailBackend()

    assert (backend.host, backend.username) == ("smtp.from-env.com", "env@example.com")


@pytest.mark.django_db
def test_sending_off_skips_emails_and_logs_it_but_the_bell_works(ravi):
    saved_row(sending_on=False)

    notify(ravi, "Trip approved")

    log = NotificationLog.objects.get(user=ravi, channel="email")
    assert (log.status, log.error) == ("skipped", "Skipped: email is switched off")
    assert len(mail.outbox) == 0 and Notification.objects.filter(user=ravi).exists()


@pytest.mark.django_db
def test_lost_key_stops_sending_at_once_and_warns_the_admin_once_a_day(ravi, settings, caplog):
    boss = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    saved_row()
    settings.EMAIL_BACKEND = SCREEN_BACKEND
    settings.EMAIL_SETTINGS_KEY = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="

    with caplog.at_level(logging.INFO):
        notify(ravi, "Trip approved", channels=["email"])
        notify(ravi, "Trip approved again", channels=["email"])

    logs = NotificationLog.objects.filter(user=ravi)
    assert {(log.status, log.attempts) for log in logs} == {("failed", 1)}  # no pointless retries
    assert logs.first().error == "Password can't be read, please type it again"
    assert Notification.objects.filter(user=boss, title=services.FAILING_TITLE).count() == 1
    assert SECRET not in caplog.text


@pytest.mark.django_db
def test_failing_server_warns_the_superuser_by_bell_not_email(ravi):
    boss = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)

    with mock.patch("core.notifications.services.send_mail", side_effect=smtplib.SMTPException("timeout")):
        notify(ravi, "Trip approved", channels=["email"])

    warning = Notification.objects.get(user=boss)
    assert warning.title == "Emails are failing: check Email settings"
    assert not NotificationLog.objects.filter(user=boss, channel="email").exists()


# --- E2: the "Send test email" button ----------------------------------------------------------------------

@pytest.mark.django_db
def test_test_button_sends_to_the_admin_with_saved_settings_and_shows_ok(client):
    boss = verified_admin(client)
    row = saved_row()

    with mock.patch("smtplib.SMTP") as smtp:
        page = client.post(f"/admin/notifications/emailsettings/{row.pk}/send-test/", follow=True)

    assert smtp.call_args.args == ("smtp.gmail.com", 587)
    smtp.return_value.login.assert_called_once_with("coin@example.com", SECRET)
    to_address = smtp.return_value.sendmail.call_args.args[1]
    assert to_address == [boss.email]
    row.refresh_from_db()
    assert row.last_test_ok is True
    assert "Test email sent to boss@example.com" in page.content.decode()
    assert "Last test:</strong>\n      OK" in page.content.decode()


@pytest.mark.django_db
def test_test_button_shows_a_wrong_password_in_plain_words_and_logs_no_secret(client, caplog):
    verified_admin(client)
    row = saved_row()
    refused = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    with mock.patch("smtplib.SMTP") as smtp, caplog.at_level(logging.INFO):
        smtp.return_value.login.side_effect = refused
        page = client.post(f"/admin/notifications/emailsettings/{row.pk}/send-test/", follow=True)

    assert "use an App Password, not your normal password" in page.content.decode()
    assert EmailSettings.objects.get().last_test_ok is False
    assert SECRET not in caplog.text and SECRET not in page.content.decode()


@pytest.mark.django_db
def test_sandbox_never_sends_even_the_test(client, settings):
    verified_admin(client)
    row = saved_row()
    settings.IS_SANDBOX = True

    with mock.patch("smtplib.SMTP") as smtp:
        page = client.post(f"/admin/notifications/emailsettings/{row.pk}/send-test/", follow=True)

    assert not smtp.called
    assert "The sandbox never sends real email" in page.content.decode()


def test_mail_errors_become_plain_words():
    row = EmailSettings(host="smtp.example.com", port=25)

    assert "did not answer" in services.plain_error(TimeoutError(), row)
    assert "Check the Mail server name" in services.plain_error(__import__("socket").gaierror(), row)
    assert "TLS for 587, SSL for 465" in services.plain_error(smtplib.SMTPServerDisconnected(), row)
