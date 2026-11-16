"""Admin base classes that apply the access layer, so admin screens follow the same rules as app screens.

- Only users whose role opens the model's app see it in admin.
- Lists and dropdowns show only rows of the user's companies (and own rows, if their role says so).
- The company choice lists only companies where the user's role opens the model's app.
- "Created by" is filled in automatically.
- The History button shows only records the user may see, without hidden fields (e.g. bank details).
"""
from itertools import pairwise

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from . import services
from .models import BaseModel


class HistoryAdmin(SimpleHistoryAdmin):
    """Admin with a History button. Old versions open only for rows in this admin's list."""

    def has_view_history_or_change_history_permission(self, request, obj=None):
        """Same rights as viewing the record itself, and only for rows this admin lists for the user."""
        listed = obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        return self.has_view_permission(request, obj) and listed

    def set_history_delta_changes(self, request, historical_records, foreign_keys_are_objs=True):
        from core.audit.services import visible_changes

        for newer, older in pairwise(historical_records):
            newer.history_delta_changes = visible_changes(newer, older, request.user)


class AppAccessAdminMixin:
    """Admin rights come from the user's roles, not from Django's per-model tick boxes."""

    def _can_open_app(self, request):
        return services.user_can_open_app(request.user, self.model._meta.app_label)

    def has_module_permission(self, request):
        return self._can_open_app(request)

    def has_view_permission(self, request, obj=None):
        return self._can_open_app(request)

    def has_add_permission(self, request):
        return self._can_open_app(request)

    def has_change_permission(self, request, obj=None):
        return self._can_open_app(request)

    def has_delete_permission(self, request, obj=None):
        return self._can_open_app(request)


class AccessModelAdmin(AppAccessAdminMixin, HistoryAdmin):
    """Use for every model built on BaseModel."""

    readonly_fields = ("created_by", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).for_user(request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if db_field.name == "company":
            kwargs["queryset"] = services.companies_for_app(request.user, self.model._meta.app_label)
        elif issubclass(related_model, BaseModel):
            kwargs["queryset"] = related_model.objects.for_user(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
