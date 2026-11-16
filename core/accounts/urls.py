from django.urls import path

from .views import OTPSetupView, OTPVerifyView

app_name = "accounts"

urlpatterns = [
    path("2fa/setup/", OTPSetupView.as_view(), name="otp_setup"),
    path("2fa/verify/", OTPVerifyView.as_view(), name="otp_verify"),
]
