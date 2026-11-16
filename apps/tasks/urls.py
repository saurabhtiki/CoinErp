from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "tasks"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="tasks:list", permanent=False), {"view": "mine"}),
    path("list/<slug:view>/", views.TaskListView.as_view(), name="list"),
    path("new/", views.TaskNewView.as_view(), name="new"),
    path("<int:pk>/", views.TaskDetailView.as_view(), name="detail"),
    path("<int:pk>/done/", views.TaskDoneView.as_view(), name="done"),
    path("<int:pk>/review/", views.TaskReviewView.as_view(), name="review"),
    path("<int:pk>/cancel/", views.TaskCancelView.as_view(), name="cancel"),
    path("<int:pk>/comments/", views.TaskCommentView.as_view(), name="comment"),
    path("<int:pk>/actions/", views.TaskActionAddView.as_view(), name="action_add"),
    path("actions/<int:pk>/<slug:change>/", views.TaskActionView.as_view(), name="action"),
    path("<int:pk>/links/", views.TaskLinkAddView.as_view(), name="link_add"),
    path("links/<int:pk>/remove/", views.TaskLinkRemoveView.as_view(), name="link_remove"),
]
