from django.urls import path

from .views import DeleteFileView, PrivateFileView, RecordFilesView

app_name = "files"

urlpatterns = [
    path("private/<path:name>", PrivateFileView.as_view(), name="private"),
    path("attachments/<int:pk>/delete/", DeleteFileView.as_view(), name="delete"),
    path("<slug:app_label>/<slug:model_name>/<int:pk>/", RecordFilesView.as_view(), name="record"),
]
