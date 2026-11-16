from django.contrib import admin

from .models import NotificationLog


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
