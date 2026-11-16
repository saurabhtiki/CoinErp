from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),  # login, logout, password reset/change
    path("accounts/", include("core.accounts.urls")),  # 2FA
    path("", include("core.urls")),
]
