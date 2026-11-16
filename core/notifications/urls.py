from django.urls import path

from .views import MarkAllReadView, NotificationListView, OpenNotificationView, SentMailView

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("<int:pk>/", OpenNotificationView.as_view(), name="open"),
    path("read-all/", MarkAllReadView.as_view(), name="read_all"),
    path("sent-mail/", SentMailView.as_view(), name="sent_mail"),
]
