import logging
import mimetypes

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic import FormView

from core.masters.services import own_photo_employee

from . import services
from .forms import OTPCodeForm

logger = logging.getLogger(__name__)
PHOTO_TYPES = {"image/png", "image/jpeg"}


class OTPSetupView(LoginRequiredMixin, FormView):
    """First-time 2FA: scan the QR code, then type a code to prove it works."""

    template_name = "accounts/otp_setup.html"
    form_class = OTPCodeForm
    success_url = "/"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and services.user_has_2fa_device(request.user):
            return redirect("accounts:otp_verify")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        device = services.get_or_create_pending_device(self.request.user)
        kwargs["qr_svg"] = mark_safe(services.qr_code_svg(device))  # SVG built by qrcode, no user input
        kwargs["secret"] = services.device_secret(device)
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        device = services.get_or_create_pending_device(self.request.user)
        if not services.confirm_device(self.request, device, form.cleaned_data["token"]):
            form.add_error("token", "That code is wrong or expired. Try the newest code in your app.")
            return self.form_invalid(form)
        return super().form_valid(form)


class OTPVerifyView(LoginRequiredMixin, FormView):
    """Every login for users who need 2FA: type the current code."""

    template_name = "accounts/otp_verify.html"
    form_class = OTPCodeForm
    success_url = "/"

    def form_valid(self, form):
        if not services.verify_login_code(self.request, form.cleaned_data["token"]):
            form.add_error("token", "That code is wrong or expired. Try the newest code in your app.")
            return self.form_invalid(form)
        return super().form_valid(form)


class MyPhotoView(LoginRequiredMixin, View):
    """Your own photo for the top bar. Only ever your own, so no other permission check is needed."""

    def get(self, request):
        employee = own_photo_employee(request.user)
        if employee is None:
            raise Http404("You have no photo yet.")
        content_type = mimetypes.guess_type(employee.profile_photo.name)[0]
        if content_type not in PHOTO_TYPES:
            logger.warning("Photo %r of user %s is not a JPG or PNG", employee.profile_photo.name, request.user.pk)
            raise Http404("Your photo is not a JPG or PNG.")
        try:
            handle = employee.profile_photo.open("rb")
        except FileNotFoundError:
            logger.error("Photo %r is in the database but missing on disk", employee.profile_photo.name)
            raise Http404("Your photo is missing on the server. Please tell your admin.") from None
        response = FileResponse(handle, content_type=content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, max-age=86400"  # the URL changes when the photo changes
        return response
