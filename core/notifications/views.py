from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from . import services

LATEST_IN_BELL = 8


class NotificationListView(LoginRequiredMixin, View):
    """All your notifications, 25 per page. For htmx (the bell) only the latest few."""

    def get(self, request):
        rows = services.notifications_for(request.user)
        if request.htmx:
            return render(request, "notifications/partials/bell_list.html", {"items": rows[:LATEST_IN_BELL]})
        page = Paginator(rows, 25).get_page(request.GET.get("page"))
        return render(request, "notifications/list.html", {"page": page})


class SentMailView(LoginRequiredMixin, View):
    """Sandbox only: the emails that were not really sent. On production this page does not exist (404)."""

    def get(self, request):
        if not settings.IS_SANDBOX:
            raise Http404("Sent mail is shown on the sandbox only.")
        page = Paginator(services.sandbox_mail_for(request.user), 25).get_page(request.GET.get("page"))
        return render(request, "notifications/sent_mail.html", {"page": page})


class OpenNotificationView(LoginRequiredMixin, View):
    """Mark as read, then go to its page (only links inside this site)."""

    def get(self, request, pk):
        notification = get_object_or_404(services.notifications_for(request.user), pk=pk)
        services.mark_read(notification)
        link = notification.link
        if link and url_has_allowed_host_and_scheme(link, allowed_hosts={request.get_host()}):
            return redirect(link)
        return redirect("notifications:list")


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        services.mark_all_read(request.user)
        return redirect("notifications:list")
