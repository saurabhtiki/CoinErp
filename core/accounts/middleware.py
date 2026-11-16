from django.shortcuts import redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect

from core.access.services import roles_require_2fa

from .services import user_has_2fa_device

# Pages a logged-in user can open before passing 2FA. Full names (with namespace), so a page
# called "login" in some other app is not let through by mistake.
OPEN_VIEW_NAMES = {"login", "logout", "accounts:otp_setup", "accounts:otp_verify", "core:healthz"}


class TwoFactorRequiredMiddleware:
    """Sends users who need 2FA to set it up or enter their code before they see anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if not user.is_authenticated or user.is_verified():
            return None
        if request.resolver_match.view_name in OPEN_VIEW_NAMES or not roles_require_2fa(user):
            return None
        target = reverse("accounts:otp_verify" if user_has_2fa_device(user) else "accounts:otp_setup")
        if request.htmx:
            return HttpResponseClientRedirect(target)
        return redirect(target)
