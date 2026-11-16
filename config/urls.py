from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),  # login, logout, password reset/change
    path("accounts/", include("core.accounts.urls")),  # 2FA
    path("masters/", include("core.masters.urls")),
    path("history/", include("core.audit.urls")),
    path("files/", include("core.files.urls")),
    path("notifications/", include("core.notifications.urls")),
    path("backups/", include("core.backups.urls")),
    path("approvals/", include("core.approvals.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("", include("core.urls")),
]
