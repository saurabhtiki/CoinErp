"""Notifications: notify() on each channel, email retries, and the bell (own messages only)."""
import logging
import smtplib
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from core.notifications.models import Notification, NotificationLog
from core.notifications.services import notify

User = get_user_model()
PASSWORD = "a-long-password-123"
SEND_MAIL = "core.notifications.services.send_mail"


@pytest.fixture
def ravi(db):
    return User.objects.create_user(email="ravi@example.com", password=PASSWORD, first_name="Ravi")


@pytest.fixture
def gita(db):
    return User.objects.create_user(email="gita@example.com", password=PASSWORD, first_name="Gita")


def statuses(user):
    return {log.channel: log.status for log in NotificationLog.objects.filter(user=user)}


def test_notify_sends_email_and_bell_message_and_logs_both(ravi, settings):
    settings.SITE_URL = "https://erp.example.com"

    notify(ravi, "Trip approved", "Your Pune trip is approved.", link="/travel/12/")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ravi@example.com"]
    assert mail.outbox[0].subject == "Trip approved"
    assert "https://erp.example.com/travel/12/" in mail.outbox[0].body
    assert Notification.objects.get(user=ravi).title == "Trip approved"
    assert statuses(ravi) == {"email": "sent", "inapp": "sent"}


def test_failed_email_is_tried_three_times_then_logged(ravi, caplog):
    with mock.patch(SEND_MAIL, side_effect=smtplib.SMTPException("SMTP timeout")) as send:
        with caplog.at_level(logging.ERROR):
            notify(ravi, "Trip approved", channels=["email"])

    log = NotificationLog.objects.get(user=ravi)
    assert send.call_count == 3
    assert (log.status, log.attempts, log.error) == ("failed", 3, "SMTP timeout")
    assert "failed after 3 tries" in caplog.text


def test_email_that_works_on_second_try_is_sent(ravi):
    with mock.patch(SEND_MAIL, side_effect=[OSError("network down"), 1]):
        notify(ravi, "Trip approved", channels=["email"])

    log = NotificationLog.objects.get(user=ravi)
    assert (log.status, log.attempts) == ("sent", 2)


def test_whatsapp_is_logged_as_not_set_up_yet(ravi):
    notify(ravi, "Trip approved", channels=["whatsapp"])

    log = NotificationLog.objects.get(user=ravi)
    assert (log.status, log.error) == ("skipped", "WhatsApp not set up yet")


def test_unknown_channel_is_an_error(ravi):
    with pytest.raises(ValueError, match="sms"):
        notify(ravi, "Hello", channels=["sms"])


def test_inactive_user_gets_no_email(ravi):
    ravi.is_active = False
    ravi.save()

    notify(ravi, "Hello", channels=["email"])

    assert mail.outbox == []
    assert statuses(ravi) == {"email": "skipped"}


def test_bell_shows_own_unread_count_and_own_messages_only(client, ravi, gita):
    notify(ravi, "For Ravi", channels=["inapp"])
    notify(gita, "For Gita", channels=["inapp"])
    client.force_login(ravi)

    page = client.get("/").content.decode()
    bell = client.get("/notifications/", HTTP_HX_REQUEST="true").content.decode()

    assert 'id="bell-count"' in page and ">1</span>" in page
    assert "For Ravi" in bell and "For Gita" not in bell
    assert "<html" not in bell


def test_bell_shows_9_plus_for_many(client, ravi):
    for number in range(12):
        notify(ravi, f"Message {number}", channels=["inapp"])
    client.force_login(ravi)

    assert ">9+</span>" in client.get("/").content.decode()


def test_no_badge_when_all_read(client, ravi):
    client.force_login(ravi)

    assert 'id="bell-count"' not in client.get("/").content.decode()


def test_opening_marks_read_and_goes_to_the_link(client, ravi):
    notify(ravi, "Trip approved", channels=["inapp"], link="/masters/vendors/")
    item = Notification.objects.get()
    client.force_login(ravi)

    response = client.get(f"/notifications/{item.pk}/")

    item.refresh_from_db()
    assert response.url == "/masters/vendors/"
    assert item.read_at is not None


def test_links_to_other_sites_are_not_followed(client, ravi):
    notify(ravi, "Click me", channels=["inapp"], link="https://evil.example.com/")
    client.force_login(ravi)

    response = client.get(f"/notifications/{Notification.objects.get().pk}/")

    assert response.url == "/notifications/"


def test_cannot_open_someone_elses_notification(client, ravi, gita):
    notify(gita, "For Gita", channels=["inapp"])
    client.force_login(ravi)

    assert client.get(f"/notifications/{Notification.objects.get().pk}/").status_code == 404
    assert Notification.objects.get().read_at is None


def test_mark_all_read_only_touches_own(client, ravi, gita):
    notify(ravi, "One", channels=["inapp"])
    notify(ravi, "Two", channels=["inapp"])
    notify(gita, "For Gita", channels=["inapp"])
    client.force_login(ravi)

    client.post("/notifications/read-all/")

    assert not Notification.objects.filter(user=ravi, read_at__isnull=True).exists()
    assert Notification.objects.filter(user=gita, read_at__isnull=True).exists()


def test_notifications_page_lists_messages(client, ravi):
    notify(ravi, "Trip approved", "Your Pune trip is approved.", channels=["inapp"])
    client.force_login(ravi)

    content = client.get("/notifications/").content.decode()

    assert "Trip approved" in content and "Your Pune trip is approved." in content
    assert "Mark all as read" in content
