from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.views.generic import FormView

from . import services
from .forms import OTPCodeForm


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
