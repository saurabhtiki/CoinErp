"""notify(): one call sends a message on several channels. Example:

    notify(ravi, "Travel request approved", "Your Pune trip is approved.", link="/travel/12/")

- "inapp": shows in the bell at once.
- "email": sent by a background job (worker), tried 3 times.
- "whatsapp": not set up yet; logged as "not sent".
Every send is written to NotificationLog.

The mail server comes from Admin -> Email settings (superuser only); see the second half of this file.
"""
import logging
import smtplib
import socket
import ssl
import time
from datetime import timedelta
from email.utils import formataddr

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage, send_mail
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend
from django.urls import reverse
from django.utils import timezone
from django_q.tasks import async_task

from .models import EmailSettings, Notification, NotificationLog

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
    if email_switched_off():
        logger.info("Email %s skipped: email is switched off in Email settings", log.pk)
        _mark(log, Status.SKIPPED, SWITCHED_OFF)
        return
    body = log.message
    if log.link:
        body = f"{body}\n\nOpen: {settings.SITE_URL.rstrip('/')}{log.link}".strip()
    waits = list(settings.NOTIFY_RETRY_WAITS)
    while True:
        log.attempts += 1
        try:
            send_mail(log.title, body, None, [log.user.email], fail_silently=False)
        except EmailSettingsError as error:  # e.g. the saved password can't be read: trying again won't help
            logger.error("Email %s to user %s not sent: %s", log.pk, log.user_id, error)
            _mark(log, Status.FAILED, str(error))
            warn_admins_email_failing(str(error))
            return
        except (smtplib.SMTPException, OSError) as error:
            logger.warning("Email %s try %s failed: %s", log.pk, log.attempts, error)
            if not waits:
                logger.error("Email %s to user %s failed after %s tries: %s", log.pk, log.user_id, log.attempts, error)
                _mark(log, Status.FAILED, str(error) or type(error).__name__)
                warn_admins_email_failing(plain_error(error))
                return
            time.sleep(waits.pop(0))
        else:
            _mark(log, Status.SENT)
            return


def notifications_for(user):
    """The user's own bell messages, newest first. Nobody sees anyone else's."""
    return Notification.objects.filter(user=user)


def sandbox_mail_for(user):
    """Emails the sandbox "sent" (it only logs them). A superuser sees all; everyone else sees their own."""
    rows = NotificationLog.objects.filter(channel=Channel.EMAIL).select_related("user")
    return rows if user.is_superuser else rows.filter(user=user)


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


# --- Email settings (Admin -> Email settings) -------------------------------------------------------------

SWITCHED_OFF = "Skipped: email is switched off"
PASSWORD_UNREADABLE = "Password can't be read, please type it again"
FAILING_TITLE = "Emails are failing: check Email settings"


class EmailSettingsError(Exception):
    """A plain-words problem with the Email settings, shown to the admin as is."""


def saved_email_settings():
    """The one saved row, or None (then the .env email lines are used)."""
    return EmailSettings.objects.first()


def email_switched_off():
    row = saved_email_settings()
    return row is not None and not row.sending_on


def _fernet():
    key = settings.EMAIL_SETTINGS_KEY
    if not key:
        logger.error("EMAIL_SETTINGS_KEY is missing in .env")
        raise EmailSettingsError(
            "EMAIL_SETTINGS_KEY is missing in .env, so the password can't be kept safe. "
            "Ask IT to add it (see docs/deploy.md)."
        )
    try:
        return Fernet(key)
    except (ValueError, TypeError) as error:
        logger.error("EMAIL_SETTINGS_KEY in .env is not a valid key: %s", type(error).__name__)
        raise EmailSettingsError(
            "EMAIL_SETTINGS_KEY in .env is not a valid key. Ask IT to make a new one (see docs/deploy.md)."
        ) from error


def encrypt_password(plain_password):
    """Scramble the password before saving. Example: "abcd efgh" -> "gAAAAAB..." (unreadable without the key)."""
    return _fernet().encrypt(plain_password.encode()).decode()


def read_password(row):
    """The saved password in plain text, only to hand to the mail server. "" when none is saved."""
    if not row.password_encrypted:
        return ""
    try:
        return _fernet().decrypt(row.password_encrypted.encode()).decode()
    except (InvalidToken, EmailSettingsError) as error:
        logger.error("Email settings password can't be read (key lost or changed): %s", type(error).__name__)
        raise EmailSettingsError(PASSWORD_UNREADABLE) from error


def password_problem(row):
    """Plain words for the red note on the screen, or "" when the password is fine."""
    try:
        read_password(row)
    except EmailSettingsError as error:
        return str(error)
    return ""


def smtp_options(row):
    """Settings for Django's SMTP sender, taken from the screen."""
    return {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "password": read_password(row),
        "use_tls": row.security == EmailSettings.Security.TLS,
        "use_ssl": row.security == EmailSettings.Security.SSL,
        "timeout": settings.EMAIL_TIMEOUT,
    }


def sender(row):
    """Example: 'Coin <coin@yourcompany.com>'."""
    return formataddr((row.from_name, row.from_address))


def plain_error(error, row=None):
    """Turn a mail error into words an admin can act on."""
    server = f"The mail server {row.host}:{row.port}" if row else "The mail server"
    if isinstance(error, EmailSettingsError):
        return str(error)
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "The mail server refused the login or password. "
            "For Gmail or Outlook use an App Password, not your normal password."
        )
    if isinstance(error, smtplib.SMTPSenderRefused):
        return "The mail server did not accept the From address. Use the mailbox you log in with."
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "The mail server refused to deliver to that address."
    if isinstance(error, socket.gaierror):
        return "Could not find the mail server. Check the Mail server name."
    if isinstance(error, (ssl.SSLError, smtplib.SMTPServerDisconnected)):
        return "The connection broke. Usually Security does not match the port: TLS for 587, SSL for 465."
    if isinstance(error, (ConnectionRefusedError, TimeoutError)):
        return f"{server} did not answer. Check the Port and Security, or ask IT whether the port is blocked."
    return f"Sending failed: {error or type(error).__name__}"


def send_test_email(row, user):
    """The "Send test email" button: one mail to the admin, with the saved settings.
    Sends for real even on a developer PC; never on the sandbox. Returns (ok, message) and remembers the result."""
    if settings.IS_SANDBOX:
        return False, "The sandbox never sends real email, so the test was not sent."
    if not user.email:
        return False, "Your login has no email address, so there is nowhere to send the test."
    try:
        connection = SmtpBackend(fail_silently=False, **smtp_options(row))
        EmailMessage(
            "Coin test email",
            "This is a test from Admin -> Email settings. If you can read it, email works.",
            sender(row),
            [user.email],
            reply_to=[row.reply_to] if row.reply_to else None,
            connection=connection,
        ).send()
    except (EmailSettingsError, smtplib.SMTPException, OSError) as error:
        logger.error("Test email for user %s failed: %s", user.pk, type(error).__name__)  # no settings in the log
        ok, message = False, plain_error(error, row)
    else:
        ok, message = True, f"Test email sent to {user.email}. Check that inbox (and spam)."
    EmailSettings.objects.filter(pk=row.pk).update(
        last_test_at=timezone.now(), last_test_ok=ok, last_test_message=message[:500]
    )
    return ok, message


def warn_admins_email_failing(reason):
    """Bell message (not email) to each superuser, at most once a day."""
    since = timezone.now() - timedelta(days=1)
    link = reverse("admin:notifications_emailsettings_changelist")
    for admin_user in get_user_model().objects.filter(is_superuser=True, is_active=True):
        if not Notification.objects.filter(user=admin_user, title=FAILING_TITLE, created_at__gte=since).exists():
            notify(admin_user, FAILING_TITLE, f"Last error: {reason}", channels=[Channel.IN_APP], link=link)
