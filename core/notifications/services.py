"""notify(): one call sends a message on several channels. Example:

    notify(ravi, "Travel request approved", "Your Pune trip is approved.", link="/travel/12/")

- "inapp": shows in the bell at once.
- "email": sent by a background job (worker), tried 3 times.
- "whatsapp": not set up yet; logged as "not sent".
Every send is written to NotificationLog.
"""
import logging
import smtplib
import time

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django_q.tasks import async_task

from .models import Notification, NotificationLog

logger = logging.getLogger(__name__)
Channel = NotificationLog.Channel
Status = NotificationLog.Status
DEFAULT_CHANNELS = (Channel.EMAIL, Channel.IN_APP)


def notify(user, title, message="", channels=DEFAULT_CHANNELS, link=""):
    """Send one message to one user. Returns the log rows (one per channel)."""
    unknown = set(channels) - set(Channel.values)
    if unknown:
        raise ValueError(f"Unknown notification channel(s): {', '.join(sorted(unknown))}")
    logs = []
    for channel in channels:
        log = NotificationLog.objects.create(user=user, channel=channel, title=title, message=message, link=link)
        if channel == Channel.IN_APP:
            Notification.objects.create(user=user, title=title, message=message, link=link)
            _mark(log, Status.SENT)
        elif channel == Channel.WHATSAPP:
            logger.info("WhatsApp to user %s skipped: not set up yet", user.pk)
            _mark(log, Status.SKIPPED, "WhatsApp not set up yet")
        else:
            async_task("core.notifications.services.send_email", log.pk)
        logs.append(log)
    return logs


def _mark(log, status, error=""):
    log.status = status
    log.error = error
    if status == Status.SENT:
        log.sent_at = timezone.now()
    log.save(update_fields=["status", "error", "sent_at", "attempts"])


def send_email(log_id):
    """Background job: send one logged email, trying 3 times before giving up."""
    log = NotificationLog.objects.select_related("user").get(pk=log_id)
    if not log.user.email or not log.user.is_active:
        logger.warning("Email %s not sent: user %s has no email or is inactive", log.pk, log.user_id)
        _mark(log, Status.SKIPPED, "User has no email address or is inactive.")
        return
    body = log.message
    if log.link:
        body = f"{body}\n\nOpen: {settings.SITE_URL.rstrip('/')}{log.link}".strip()
    waits = list(settings.NOTIFY_RETRY_WAITS)
    while True:
        log.attempts += 1
        try:
            send_mail(log.title, body, None, [log.user.email], fail_silently=False)
        except (smtplib.SMTPException, OSError) as error:
            logger.warning("Email %s try %s failed: %s", log.pk, log.attempts, error)
            if not waits:
                logger.error("Email %s to user %s failed after %s tries: %s", log.pk, log.user_id, log.attempts, error)
                _mark(log, Status.FAILED, str(error) or type(error).__name__)
                return
            time.sleep(waits.pop(0))
        else:
            _mark(log, Status.SENT)
            return


def notifications_for(user):
    """The user's own bell messages, newest first. Nobody sees anyone else's."""
    return Notification.objects.filter(user=user)


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return notifications_for(user).filter(read_at__isnull=True).count()


def mark_read(notification):
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])


def mark_all_read(user):
    notifications_for(user).filter(read_at__isnull=True).update(read_at=timezone.now())
