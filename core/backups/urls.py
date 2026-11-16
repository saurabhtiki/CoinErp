from django.urls import path

from .views import BackupDownloadView, BackupListView, BackupNowView

app_name = "backups"

urlpatterns = [
    path("", BackupListView.as_view(), name="list"),
    path("now/", BackupNowView.as_view(), name="now"),
    path("<int:pk>/download/", BackupDownloadView.as_view(), name="download"),
]
