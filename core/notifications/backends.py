"""Mail backend used on real servers: Django's SMTP sender, but with Admin -> Email settings.

Until the screen is saved, the .env email lines are used (nothing breaks on the update day).
Every app that sends mail (Tasks, password reset, ...) goes through here without any change.
"""
import logging

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

from . import services

logger = logging.getLogger(__name__)


class EmailBackend(SmtpBackend):
    def __init__(self, fail_silently=False, **kwargs):
        self.screen = services.saved_email_settings()
        if self.screen:
            kwargs = {**kwargs, **services.smtp_options(self.screen)}  # raises EmailSettingsError if unreadable
        super().__init__(fail_silently=fail_silently, **kwargs)

    def send_messages(self, email_messages):
        if self.screen and not self.screen.sending_on:
            logger.info("%s email(s) skipped: email is switched off in Email settings", len(email_messages))
            return 0
        if self.screen:
            for message in email_messages:
                if message.from_email == settings.DEFAULT_FROM_EMAIL:
                    message.from_email = services.sender(self.screen)
                if self.screen.reply_to and not message.reply_to:
                    message.reply_to = [self.screen.reply_to]
        return super().send_messages(email_messages)
