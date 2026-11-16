"""Login, invite and 2FA rules. Views and middleware call these; they hold no logic themselves."""
import logging
from base64 import b32encode

import qrcode
import qrcode.image.svg
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp import login as otp_login
from django_otp import match_token, user_has_device
from django_otp.plugins.otp_totp.models import TOTPDevice

logger = logging.getLogger(__name__)


def lockout_username(request, credentials=None):
    """Name used by django-axes to count wrong passwords. Lower-case, so changing case can't dodge a lock."""
    username = (credentials or {}).get("username") or request.POST.get("username", "")
    return username.strip().lower()


def user_needs_2fa(user):
    """Superusers always need 2FA; others only if one of their roles says so."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.company_roles.filter(role__requires_2fa=True).exists()


def user_has_2fa_device(user):
    return user_has_device(user, confirmed=True)


def send_invite(user, request):
    """Email a new user a link to set their own password (Django's built-in reset link)."""
    link = request.build_absolute_uri(
        reverse(
            "password_reset_confirm",
            kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                "token": default_token_generator.make_token(user),
            },
        )
    )
    context = {"user": user, "link": link}
    subject = render_to_string("registration/invite_subject.txt", context).strip()
    body = render_to_string("registration/invite_email.txt", context)
    try:
        send_mail(subject, body, None, [user.email])
    except OSError:
        logger.exception("Invite email to %s could not be sent", user.email)
        raise
    logger.info("Invite sent to %s", user.email)


def get_or_create_pending_device(user):
    """An unconfirmed authenticator entry, kept until the user types a correct code."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=False)
    return device


def qr_code_svg(device):
    """QR picture (SVG text) the user scans with Google Authenticator or similar."""
    image = qrcode.make(device.config_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    return image.to_string(encoding="unicode")


def device_secret(device):
    """The key in text form, for users who type it into the app instead of scanning."""
    return b32encode(device.bin_key).decode()


def confirm_device(request, device, token):
    """Finish 2FA setup. Returns True if the code was right."""
    if not device.verify_token(token):
        logger.warning("Wrong 2FA setup code for %s", request.user.email)
        return False
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    otp_login(request, device)
    return True


def verify_login_code(request, token):
    """Check the 6-digit code at login. Returns True if it matched one of the user's devices."""
    device = match_token(request.user, token)
    if device is None:
        logger.warning("Wrong 2FA login code for %s", request.user.email)
        return False
    otp_login(request, device)
    return True
