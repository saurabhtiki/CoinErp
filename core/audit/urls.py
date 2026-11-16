from django.urls import path

from .views import RecordHistoryView

app_name = "audit"

urlpatterns = [
    path("<slug:app_label>/<slug:model_name>/<int:pk>/", RecordHistoryView.as_view(), name="record"),
]
