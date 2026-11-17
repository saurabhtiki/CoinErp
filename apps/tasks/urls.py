from django.urls import path
from django.views.generic import RedirectView

from . import rule_views, views

app_name = "tasks"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="tasks:list", permanent=False), {"view": "mine"}),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
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
    # repeating rules
    path("repeating/", rule_views.RuleListView.as_view(), name="rules"),
    path("repeating/new/", rule_views.RuleNewView.as_view(), name="rule_new"),
    path("repeating/preview/", rule_views.RulePreviewView.as_view(), name="rule_preview"),
    path("repeating/run/", rule_views.RuleRunView.as_view(), name="rule_run"),
    path("repeating/<int:pk>/", rule_views.RuleDetailView.as_view(), name="rule"),
    path("repeating/<int:pk>/pause/", rule_views.RulePauseView.as_view(), name="rule_pause"),
    path("repeating/<int:pk>/actions/", rule_views.RuleActionAddView.as_view(), name="rule_action_add"),
    path("repeating/actions/<int:pk>/remove/", rule_views.RuleActionRemoveView.as_view(), name="rule_action_remove"),
    # holidays and off Saturdays
    path("holidays/", rule_views.HolidayListView.as_view(), name="holidays"),
    path("holidays/saturdays/", rule_views.SaturdaysView.as_view(), name="saturdays"),
    path("holidays/<int:pk>/remove/", rule_views.HolidayRemoveView.as_view(), name="holiday_remove"),
]
