from django.urls import path

from .views import ActView, MyApprovalsView, RecordApprovalView

app_name = "approvals"

urlpatterns = [
    path("", MyApprovalsView.as_view(), name="mine"),
    path("<int:pk>/act/", ActView.as_view(), name="act"),
    path("record/<slug:app_label>/<slug:model_name>/<int:pk>/", RecordApprovalView.as_view(), name="record"),
]
