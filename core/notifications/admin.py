from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from core.access import services as access
from core.access.admin import HistoryAdmin

from . import services
from .forms import EmailSettingsForm
from .models import EmailSettings, NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Read-only list of every send, to find failed emails."""

    list_display = ["created_at", "user", "channel", "title", "status", "attempts", "error"]
    list_filter = ["status", "channel"]
    search_fields = ["user__email", "title"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmailSettings)
class EmailSettingsAdmin(HistoryAdmin):
    """One page (one row) for the mailbox that sends all emails. Superuser only.
    History records who changed what, never the password."""

    form = EmailSettingsForm
    change_form_template = "admin/notifications/emailsettings/change_form.html"
    fieldsets = [
        (None, {"fields": ["sending_on"]}),
        ("Mail server", {"fields": ["host", "port", "security", "username", "password"]}),
        ("Sender", {"fields": ["from_name", "from_address", "reply_to"]}),
    ]

    def _allowed(self, request):
        return access.can_manage_email_settings(request.user)

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request) and not EmailSettings.objects.exists()  # only one row

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """There is only one row: go straight to it (or to "add" the first time)."""
        if not self._allowed(request):
            return super().changelist_view(request, extra_context)  # Django answers "no access"
        row = services.saved_email_settings()
        if row:
            return redirect("admin:notifications_emailsettings_change", row.pk)
        return redirect("admin:notifications_emailsettings_add")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        row = EmailSettings.objects.filter(pk=object_id).first()
        extra_context = {**(extra_context or {}), "password_problem": row and services.password_problem(row)}
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        send_test = self.admin_site.admin_view(require_POST(self.send_test_view))
        return [path("<int:pk>/send-test/", send_test, name="notifications_emailsettings_send_test"),
                *super().get_urls()]

    def send_test_view(self, request, pk):
        if not self._allowed(request):
            messages.error(request, "Only the group admin may test the email settings.")
            return redirect("admin:index")
        row = get_object_or_404(EmailSettings, pk=pk)
        ok, message = services.send_test_email(row, request.user)
        messages.add_message(request, messages.SUCCESS if ok else messages.ERROR, message)
        return redirect(reverse("admin:notifications_emailsettings_change", args=[row.pk]))
