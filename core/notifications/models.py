from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class Notification(models.Model):
    """One message in a user's bell. Example: "Travel request approved" with a link to the request."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True, help_text="Page to open, e.g. /tasks/12/")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "read_at"], name="notification_unread_idx")]

    def __str__(self):
        return self.title


class NotificationLog(models.Model):
    """Every send on every channel. Example: email to Ravi, failed, "SMTP timeout"."""

    class Channel(models.TextChoices):
        IN_APP = "inapp", "In-app"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting to send"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Not sent"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.user}: {self.title}"


class EmailSettings(models.Model):
    """The one mailbox that sends all emails, set up by the group admin in Admin.
    Example: smtp.gmail.com, port 587, TLS, coin@yourcompany.com, "Coin".
    Until this is saved, the email lines in .env are used."""

    class Security(models.TextChoices):
        TLS = "tls", "TLS (port 587)"
        SSL = "ssl", "SSL (port 465)"
        NONE = "none", "None"

    sending_on = models.BooleanField(
        "Sending on", default=True, help_text="Untick to stop all emails. The bell still works."
    )
    host = models.CharField("Mail server", max_length=200, help_text="Your provider's SMTP server, e.g. smtp.gmail.com")
    port = models.PositiveIntegerField(default=587, help_text="587 (TLS) is usual; 465 for SSL")
    security = models.CharField(
        max_length=4, choices=Security.choices, default=Security.TLS, help_text="TLS for port 587, SSL for 465"
    )
    username = models.CharField(
        "Login (mailbox)", max_length=200, blank=True, help_text="The mailbox that sends, e.g. coin@yourcompany.com"
    )
    password_encrypted = models.TextField(blank=True, editable=False)  # never shown, never in History
    from_name = models.CharField("From name", max_length=100, default="Coin", help_text="Name people see as sender")
    from_address = models.EmailField("From address", help_text="Usually the same as the login")
    reply_to = models.EmailField(
        "Reply-to", blank=True, help_text="Optional. Where replies go, e.g. office@yourcompany.com"
    )
    last_test_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_test_ok = models.BooleanField(null=True, editable=False)
    last_test_message = models.CharField(max_length=500, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(
        excluded_fields=["password_encrypted", "last_test_at", "last_test_ok", "last_test_message", "updated_at"]
    )

    class Meta:
        verbose_name = "Email settings"
        verbose_name_plural = "Email settings"

    def __str__(self):
        return f"Email settings ({self.host})"
